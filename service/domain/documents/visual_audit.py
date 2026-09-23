"""Mandatory bounded visual review for final Document Forge builds."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from service.domain.client import create_chat_completion, list_qualified_models
from service.domain.client.model_requirements import ModelRequirement
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.utils import pick_text_model
from service.domain.tools.workspace_client import WorkspaceUnavailable, call, download_binary
from service.domain.usage_ledger import UsageKind

AUDIT_VERSION = 1
PAGES_PER_CALL = 4
MAX_PAGES = 200
MAX_PAGE_BYTES = 16 * 1024 * 1024
VISUAL_CODES = frozenset(
    {
        "visual_blank_page",
        "visual_clipping",
        "visual_overlap",
        "visual_readability",
        "visual_table_overflow",
        "visual_image_quality",
        "visual_header_footer",
        "visual_composition",
    }
)
_AUDIT_FUNCTION = "submit_visual_audit"
_AUDIT_TOOL = {
    "type": "function",
    "function": {
        "name": _AUDIT_FUNCTION,
        "description": "Return the bounded visual-layout audit for the supplied PDF pages.",
        "parameters": {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "True only when none of the supplied pages has a layout defect.",
                },
                "issues": {
                    "type": "array",
                    "description": "Bounded layout defects found on the supplied pages.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": sorted(VISUAL_CODES),
                                "description": "Closed diagnostic code for the layout defect.",
                            },
                            "page": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_PAGES,
                                "description": "One-based page number containing the defect.",
                            },
                        },
                        "required": ["code", "page"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["passed", "issues"],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True, slots=True)
class VisualAuditResult:
    status: str
    passed: bool
    retryable: bool
    diagnostics: tuple[dict[str, int | str], ...] = ()


def _parse_result(
    content: str | dict[str, Any], pages: frozenset[int]
) -> tuple[bool, list[dict[str, object]]]:
    if isinstance(content, dict):
        raw = content
    else:
        value = str(content or "").strip()
        if value.startswith("```"):
            value = value.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            raw = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError("invalid visual audit response") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("passed"), bool):
        raise ValueError("invalid visual audit response")
    issues = raw.get("issues")
    if not isinstance(issues, list):
        raise ValueError("invalid visual audit response")
    normalized: list[dict[str, object]] = []
    for item in issues[:100]:
        if not isinstance(item, dict):
            raise ValueError("invalid visual audit response")
        code = str(item.get("code") or "")
        page = item.get("page")
        if code not in VISUAL_CODES or not isinstance(page, int) or page not in pages:
            raise ValueError("invalid visual audit response")
        normalized.append({"code": code, "page": page, "count": 1})
    if raw["passed"] and normalized:
        raise ValueError("invalid visual audit response")
    return bool(raw["passed"]), normalized


def _audit_tool_arguments(response: Any) -> dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    calls = getattr(message, "tool_calls", None) or []
    if len(calls) != 1:
        raise ValueError("invalid visual audit response")
    function = getattr(calls[0], "function", None)
    if function is None or getattr(function, "name", None) != _AUDIT_FUNCTION:
        raise ValueError("invalid visual audit response")
    arguments = getattr(function, "arguments", None)
    if isinstance(arguments, dict):
        return arguments
    try:
        parsed = json.loads(str(arguments or ""))
    except (TypeError, ValueError):
        raise ValueError("invalid visual audit response") from None
    if not isinstance(parsed, dict):
        raise ValueError("invalid visual audit response")
    return parsed


def _messages(images: list[tuple[int, bytes]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Inspect every supplied PDF page as a finished document. Use only the "
                "required submit_visual_audit function. Mark passed=true only when no "
                "listed visual defect is present. A deliberately sparse page with a small "
                "but readable title or short statement is valid: visual_blank_page means "
                "that no visible document content exists at all. Do not report composition "
                "merely because the requested document is minimalist. Allowed codes: "
                + ", ".join(sorted(VISUAL_CODES))
                + "."
            ),
        }
    ]
    for page, payload in images:
        content.extend(
            [
                {"type": "text", "text": f"Page {page}."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(payload).decode("ascii"),
                        "detail": "high",
                    },
                },
            ]
        )
    return [
        {
            "role": "system",
            "content": (
                "Perform a technical visual-layout audit. Do not summarize or return document "
                "content. Return no prose: call the required function with bounded codes only."
            ),
        },
        {"role": "user", "content": content},
    ]


def _page_has_visible_ink(payload: bytes) -> bool:
    """Confirm that a trusted raster page is not actually blank.

    Vision models occasionally classify deliberately minimal one-line documents
    as blank even though the rendered glyphs are visible. ``visual_blank_page``
    has a narrow meaning (no visible document content), so a deterministic pixel
    check may safely reject that one false-positive code. It does not suppress
    clipping, readability, composition, or any other visual diagnosis.
    """

    try:
        with Image.open(BytesIO(payload)) as image:
            if image.width < 1 or image.height < 1 or image.width > 20_000 or image.height > 20_000:
                return False
            grayscale = image.convert("L")
            grayscale.thumbnail((320, 320))
            pixels = tuple(grayscale.getdata())
    except (OSError, ValueError, UnidentifiedImageError):
        return False
    ink = sum(value < 245 for value in pixels)
    return ink >= max(24, len(pixels) // 5_000)


def _reconcile_blank_diagnostics(
    issues: list[dict[str, object]],
    images: list[tuple[int, bytes]],
) -> list[dict[str, object]]:
    visible = {page for page, payload in images if _page_has_visible_ink(payload)}
    return [
        item
        for item in issues
        if not (item.get("code") == "visual_blank_page" and item.get("page") in visible)
    ]


async def _report(
    ref: dict[str, Any],
    build_id: str,
    audit: dict[str, Any],
    *,
    passed: bool,
    retryable: bool,
    diagnostics: list[dict[str, object]],
) -> dict[str, Any]:
    return await call(
        ref,
        f"documents/builds/{build_id}/visual-audit/result",
        {
            "source_digest": audit["source_digest"],
            "artifact_sha256": audit["artifact_sha256"],
            "passed": passed,
            "retryable": retryable,
            "audit_version": AUDIT_VERSION,
            "diagnostics": diagnostics,
        },
    )


async def audit_document_build(
    ref: dict[str, Any],
    build_id: str,
    *,
    execution: RunExecutionContext | None = None,
) -> VisualAuditResult:
    """Claim, review and attest one exact final build."""

    execution = require_execution(execution)
    claimed = await call(ref, f"documents/builds/{build_id}/visual-audit/claim", {})
    audit = claimed.get("audit")
    if not isinstance(audit, dict):
        return VisualAuditResult("invalid", False, False)
    page_count = int(audit.get("page_count") or 0)
    if page_count < 1 or page_count > MAX_PAGES:
        await _report(ref, build_id, audit, passed=False, retryable=False, diagnostics=[])
        return VisualAuditResult("page_limit", False, False)
    models = await list_qualified_models(ModelRequirement(vision=True, tools=True))
    model = pick_text_model(models)
    if not model:
        await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        return VisualAuditResult("vision_unavailable", False, True)
    diagnostics: list[dict[str, object]] = []
    try:
        for start in range(1, page_count + 1, PAGES_PER_CALL):
            page_numbers = list(range(start, min(page_count + 1, start + PAGES_PER_CALL)))
            images: list[tuple[int, bytes]] = []
            for page in page_numbers:
                payload, _headers = await download_binary(
                    ref,
                    f"documents/builds/{build_id}/visual-pages/{page}",
                    max_bytes=MAX_PAGE_BYTES,
                )
                images.append((page, payload))
            result = await invoke_model_call(
                create_chat_completion,
                model=model,
                kind=UsageKind.DOCUMENT_VISUAL_AUDIT,
                execution=execution,
                messages=_messages(images),
                temperature=0,
                max_tokens=600,
                tools=[_AUDIT_TOOL],
                tool_choice={"type": "function", "function": {"name": _AUDIT_FUNCTION}},
                pin_provider=(
                    execution.provider_snapshot.owner_for(model)
                    if execution.provider_snapshot is not None
                    else None
                ),
            )
            passed, issues = _parse_result(
                _audit_tool_arguments(result.response), frozenset(page_numbers)
            )
            issues = _reconcile_blank_diagnostics(issues, images)
            if not issues:
                passed = True
            diagnostics.extend(issues)
            if not passed and not issues:
                raise ValueError("invalid visual audit response")
        passed = not diagnostics
        status = await _report(
            ref,
            build_id,
            audit,
            passed=passed,
            retryable=False,
            diagnostics=diagnostics,
        )
        if status.get("state") == "ready":
            return VisualAuditResult("passed", True, False)
        return VisualAuditResult("failed", False, False, tuple(diagnostics))
    except WorkspaceUnavailable:
        try:
            await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        except WorkspaceUnavailable:
            pass
        return VisualAuditResult("workspace_unavailable", False, True)
    except Exception:
        try:
            await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        except WorkspaceUnavailable:
            pass
        return VisualAuditResult("vision_unavailable", False, True)


__all__ = ["AUDIT_VERSION", "VisualAuditResult", "audit_document_build"]
