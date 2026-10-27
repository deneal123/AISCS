"""Mandatory bounded visual review for final Document Forge builds."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from service.domain.client import create_chat_completion, list_qualified_models
from service.domain.client.models.requirements import ModelRequirement
from service.domain.client.protocol.failures import classify_provider_failure
from service.domain.execution.context import RunExecutionContext, require_execution
from service.domain.execution.model import invoke_model_call
from service.domain.subagents.utils import pick_text_model
from service.domain.tools.workspace.client import WorkspaceUnavailable, call, download_binary
from service.domain.usage.ledger import UsageKind, UsageLedger
from service.shared import deadline

from .repair_provenance import PageBlocks, page_provenance

AUDIT_VERSION = 1
logger = logging.getLogger(__name__)
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
        "description": "Вернуть результаты проверки вёрстки предоставленных страниц PDF.",
        "parameters": {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "Значение true — только если на всех страницах нет дефектов.",
                },
                "issues": {
                    "type": "array",
                    "maxItems": 100,
                    "description": "Дефекты вёрстки предоставленных страниц из допустимого списка.",
                    "items": {
                        "type": "object",
                        "description": "Один дефект вёрстки предоставленной страницы PDF.",
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": sorted(VISUAL_CODES),
                                "description": "Код дефекта вёрстки из закрытого списка.",
                            },
                            "page": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_PAGES,
                                "description": "Номер страницы с дефектом, начиная с единицы.",
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
    block_pages: PageBlocks = field(default=(), repr=False)


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
    if (
        not isinstance(raw, dict)
        or set(raw) != {"passed", "issues"}
        or not isinstance(raw.get("passed"), bool)
    ):
        raise ValueError("invalid visual audit response")
    issues = raw.get("issues")
    if not isinstance(issues, list) or len(issues) > 100:
        raise ValueError("invalid visual audit response")
    if not raw["passed"] and not issues:
        raise ValueError("invalid visual audit response")
    normalized: list[dict[str, object]] = []
    for item in issues:
        if not isinstance(item, dict) or set(item) != {"code", "page"}:
            raise ValueError("invalid visual audit response")
        code = str(item.get("code") or "")
        page = item.get("page")
        if code not in VISUAL_CODES or type(page) is not int or page not in pages:
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
                "Проверь каждую предоставленную страницу PDF как готовый документ. Используй "
                "только обязательную функцию submit_visual_audit. Устанавливай passed=true "
                "только при отсутствии всех перечисленных визуальных дефектов. Страница "
                "с намеренно редким содержанием, небольшим читаемым заголовком или коротким "
                "утверждением допустима: visual_blank_page означает полное отсутствие "
                "видимого содержания. Не отмечай дефект композиции лишь из-за минималистичного "
                "оформления запрошенного документа. Допустимые коды: "
                + ", ".join(sorted(VISUAL_CODES))
                + "."
            ),
        }
    ]
    for page, payload in images:
        content.extend(
            [
                {"type": "text", "text": f"Страница {page}."},
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
                "Выполни техническую проверку вёрстки. Не пересказывай и не возвращай "
                "содержание документа. Без текстовых пояснений: вызови обязательную функцию "
                "только с кодами из допустимого списка."
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


async def _persist_usage(
    checkpoint: Callable[[UsageLedger], Awaitable[None]] | None,
    execution: RunExecutionContext,
) -> None:
    if checkpoint is not None:
        await checkpoint(execution.usage)


def _unavailable_status(stage: str) -> str:
    return "unavailable" if stage == "checkpoint" else "vision_unavailable"


async def audit_document_build(
    ref: dict[str, Any],
    build_id: str,
    *,
    execution: RunExecutionContext | None = None,
    usage_checkpoint: Callable[[UsageLedger], Awaitable[None]] | None = None,
) -> VisualAuditResult:
    """Claim, review and attest one exact final build."""

    execution = require_execution(execution)
    claimed = await call(ref, f"documents/builds/{build_id}/visual-audit/claim", {})
    audit = claimed.get("audit") if isinstance(claimed, dict) else None
    if (
        not isinstance(audit, dict)
        or type(audit.get("page_count")) is not int
        or any(
            not isinstance(audit.get(key), str) or re.fullmatch(r"[a-f0-9]{64}", audit[key]) is None
            for key in ("source_digest", "artifact_sha256")
        )
    ):
        logger.warning("document_visual_audit stage=claim code=invalid")
        return VisualAuditResult("invalid", False, False)
    page_count = audit["page_count"]
    if page_count < 1 or page_count > MAX_PAGES:
        await _report(ref, build_id, audit, passed=False, retryable=False, diagnostics=[])
        return VisualAuditResult("page_limit", False, False)
    diagnostics: list[dict[str, object]] = []
    stage = "qualification"
    try:
        models = await list_qualified_models(ModelRequirement(vision=True, tools=True))
        model = pick_text_model(models)
        if not model:
            await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
            return VisualAuditResult("vision_unavailable", False, True)
        for start in range(1, page_count + 1, PAGES_PER_CALL):
            if deadline.must_finalize():
                await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
                return VisualAuditResult("timeout", False, True)
            page_numbers = list(range(start, min(page_count + 1, start + PAGES_PER_CALL)))
            images: list[tuple[int, bytes]] = []
            stage = "raster"
            for page in page_numbers:
                payload, _headers = await download_binary(
                    ref,
                    f"documents/builds/{build_id}/visual-pages/{page}",
                    max_bytes=MAX_PAGE_BYTES,
                )
                images.append((page, payload))
            stage = "checkpoint"
            await _persist_usage(usage_checkpoint, execution)
            stage = "provider"
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
            stage = "checkpoint"
            await _persist_usage(usage_checkpoint, execution)
            stage = "protocol"
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
        stage = "attestation"
        status = await _report(
            ref,
            build_id,
            audit,
            passed=passed,
            retryable=False,
            diagnostics=diagnostics,
        )
        if passed and status.get("state") == "ready":
            return VisualAuditResult("passed", True, False)
        return VisualAuditResult(
            "failed",
            False,
            False,
            tuple(diagnostics),
            page_provenance(audit.get("block_pages"), page_count),
        )
    except asyncio.CancelledError:
        # Hard budget/user cancellation must release a known claim, but cannot
        # downgrade an already committed ready build (sidecar guards that state).
        try:
            async with asyncio.timeout(5):
                await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        except Exception:
            logger.warning("document_visual_audit stage=cancel code=unavailable")
        raise
    except WorkspaceUnavailable as exc:
        logger.warning("document_visual_audit stage=%s code=%s", stage, exc.code.value)
        try:
            await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        except WorkspaceUnavailable:
            pass
        return VisualAuditResult("workspace_unavailable", False, True)
    except Exception as exc:
        code = "invalid" if stage == "protocol" else classify_provider_failure(exc).code.value
        logger.warning("document_visual_audit stage=%s code=%s", stage, code)
        try:
            await _report(ref, build_id, audit, passed=False, retryable=True, diagnostics=[])
        except WorkspaceUnavailable:
            pass
        return VisualAuditResult(_unavailable_status(stage), False, True)


__all__ = ["AUDIT_VERSION", "VisualAuditResult", "audit_document_build"]
