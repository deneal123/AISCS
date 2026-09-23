"""Live certification for the deterministic Document Forge path.

The backend fixture is received through stdin and is never printed.  The smoke
executes the real ``pdf_gen`` subagent, downloads the produced PDF through the
authenticated workspace boundary, and verifies its registered digest.  Output
is intentionally aggregate-only so workspace credentials and artifact details
cannot become CI log material.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from service.domain.client.registry import initialize_run_provider_admission
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.domain.subagents.pdf_generation import PDFGenerationAgent
from service.domain.tools.workspace_client import download_binary
from service.events import AgentEvent, EventType
from service.presentation.cli.gigachat_smoke_support import (
    GigaChatSmokeFailure,
    bounded_failure_code,
    require_tool_model,
)
from service.schemas.agents import ModalityAttachment, UserContext

_MODEL = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-3-Lightning").strip()
_REQUEST = 'Создай PDF-файл, в котором напиши "тест"'
_REQUEST_2 = 'Создай PDF-файл, в котором напиши "тест 2"'
_MAX_PDF_BYTES = 32 * 1024 * 1024
_DOCUMENT_ATTACHMENT_KIND = "document"


@dataclass(frozen=True, slots=True)
class _Case:
    name: str
    request: str
    attachments: tuple[ModalityAttachment, ...] = ()


class _SmokeAgent(PDFGenerationAgent):
    """Capture only the private final build status for bounded smoke assertions."""

    final_status: dict[str, Any] | None = None

    async def _emit_final_status(self, final_status, *, usage_meta, model_meta):
        self.final_status = final_status if isinstance(final_status, dict) else None
        async for event in super()._emit_final_status(
            final_status,
            usage_meta=usage_meta,
            model_meta=model_meta,
        ):
            yield event


def _cases() -> tuple[_Case, ...]:
    article = (
        "# Проверяемый материал\n\n"
        "Надёжный PDF-конвейер разделяет semantic authoring и доверенный renderer. "
        "Сборка выполняется в изолированном контейнере и завершается аудитом.\n\n"
        "Источник: [Document engineering study](https://doi.org/10.1000/s36-smoke), "
        "2025. DOI: 10.1000/s36-smoke."
    )
    digest = hashlib.sha256(article.encode()).hexdigest()
    review_material = (
        "# Review article materials\n\n"
        "## Topic\n"
        "Reliability of document-generation systems based on large language models.\n\n"
        "## Source 1\n"
        "Lewis P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP "
        "Tasks. NeurIPS 2020. DOI: 10.48550/arXiv.2005.11401\n"
        "https://arxiv.org/abs/2005.11401\n\n"
        "## Source 2\n"
        "Ji Z. et al. Survey of Hallucination in Natural Language Generation. ACM "
        "Computing Surveys, 2023. DOI: 10.1145/3571730\n"
        "https://doi.org/10.1145/3571730\n\n"
        "## Requirements\n"
        "Compare the approaches, describe limitations, and formulate conclusions. "
        "Do not add sources absent from these materials.\n"
    )
    review_digest = hashlib.sha256(review_material.encode()).hexdigest()
    cases = (
        _Case("literal", _REQUEST),
        _Case("literal_2", _REQUEST_2),
        _Case(
            "attachment_article",
            "Напиши по прикреплённому материалу краткую статью в PDF.",
            (
                ModalityAttachment(
                    kind=_DOCUMENT_ATTACHMENT_KIND,
                    name="s36-material.md",
                    file_id="00000000-0000-0000-0000-000000000036",
                    mime_type="text/markdown",
                    digest=digest,
                    content=article,
                ),
            ),
        ),
        _Case(
            "attachment_review",
            "Напиши по прикреплённым материалам обзорную статью в PDF.",
            (
                ModalityAttachment(
                    kind=_DOCUMENT_ATTACHMENT_KIND,
                    name="materialy-dlya-obzornoi-stati (1).md",
                    file_id="00000000-0000-0000-0000-000000000037",
                    mime_type="text/markdown",
                    digest=review_digest,
                    content=review_material,
                ),
            ),
        ),
    )
    selected = os.getenv("S36_SMOKE_CASE", "").strip()
    return tuple(case for case in cases if not selected or case.name == selected)


def _read_private_fixture() -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise GigaChatSmokeFailure("invalid_smoke_input") from None
    ref = payload.get("workspace_ref") if isinstance(payload, dict) else None
    if not isinstance(ref, dict):
        raise GigaChatSmokeFailure("invalid_smoke_input")
    required = ("workspace_id", "token", "user_id", "coordination_capability")
    if any(not str(ref.get(field) or "").strip() for field in required):
        raise GigaChatSmokeFailure("invalid_smoke_input")
    return dict(ref)


def _artifact(events: list[AgentEvent]) -> dict[str, Any]:
    for event in events:
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        artifacts = metadata.get("document_artifacts")
        if not isinstance(artifacts, list):
            continue
        for artifact in artifacts:
            if isinstance(artifact, dict) and artifact.get("role") == "pdf":
                return artifact
    raise GigaChatSmokeFailure("artifact_missing")


def _assert_terminal(
    events: list[AgentEvent], *, expect_semantic_authoring: bool
) -> tuple[str, set[str]]:
    completed = [event for event in events if event.type == EventType.AGENT_COMPLETE]
    if len(completed) != 1:
        print(
            "document terminal probe: "
            f"events={len(events)} completed={len(completed)} "
            f"status={sum(event.type == EventType.STATUS_UPDATE for event in events)}"
        )
        raise GigaChatSmokeFailure("terminal_invalid")
    metadata = completed[0].metadata if isinstance(completed[0].metadata, dict) else {}
    requested = str(metadata.get("requested_authoring_model") or "")
    actual = str(metadata.get("actual_authoring_model") or "")
    if requested != _MODEL or actual != _MODEL:
        raise GigaChatSmokeFailure("model_mismatch")
    outcome = str(metadata.get("document_outcome") or metadata.get("execution_status") or "")
    stages = {
        str(status.get("stage") or "")
        for event in events
        if isinstance(event.metadata, dict)
        for status in [event.metadata.get("document_status")]
        if isinstance(status, dict)
    }
    required_stages = {"intent", "evidence"}
    if expect_semantic_authoring:
        required_stages.add("outline")
    if outcome in {"draft_ready", "completed", "deferred"}:
        required_stages.update({"source_publish", "compile"})
        if expect_semantic_authoring:
            required_stages.add("section_authoring")
    if outcome in {"completed", "deferred"}:
        required_stages.update({"deterministic_audit", "visual_audit", "delivery"})
    if not required_stages.issubset(stages):
        raise GigaChatSmokeFailure("stage_contract_invalid")
    return outcome, stages


async def _run_case(ref: dict[str, Any], case: _Case) -> tuple[str, int, int, int]:
    resources = PrivateRunResources.from_request(workspace_ref=ref)
    context = UserContext(
        user_id=str(ref["user_id"]),
        request_time=datetime.now(UTC),
        thread_id=str(ref.get("thread_id") or "s36-document-live"),
        workspace_ref=ref,
        current_attachments=list(case.attachments) or None,
    )
    with use_run_execution(resources) as execution:
        await initialize_run_provider_admission(execution)
        agent = _SmokeAgent({"model": _MODEL})
        events = [
            event
            async for event in agent.process(
                case.request,
                context,
            )
        ]
        outcome, stages = _assert_terminal(
            events,
            expect_semantic_authoring=not case.name.startswith("literal"),
        )
        if outcome not in {"completed", "deferred"}:
            status = agent.final_status or {}
            diagnostics = status.get("diagnostics")
            codes = sorted(
                {
                    (
                        str(item.get("code") or "unknown")
                        if isinstance(item, dict)
                        else str(item or "unknown").split(":", 1)[0]
                    )
                    for item in diagnostics or []
                }
            )
            print(
                "document terminal: "
                f"outcome={outcome or 'unknown'} "
                f"stage={str(status.get('stage') or 'unknown')} "
                f"code={str(status.get('failure_code') or 'unknown')} "
                f"reason={str(status.get('authoring_rejection_reason') or 'none')} "
                f"accepted_sections={int(status.get('accepted_sections') or 0)} "
                f"model_calls={execution.usage.bounded_summary()['call_count']} "
                f"diagnostic_count={len(diagnostics or [])} "
                f"diagnostics={','.join(codes) or 'none'}"
            )
            raise GigaChatSmokeFailure("document_not_ready")
        artifact = _artifact(events)
        build_id = str(artifact.get("build_id") or "")
        artifact_id = str(artifact.get("artifact_id") or "")
        expected_digest = str(artifact.get("sha256") or "").lower()
        if not build_id or not artifact_id or len(expected_digest) != 64:
            raise GigaChatSmokeFailure("artifact_contract_invalid")
        content, headers = await download_binary(
            ref,
            f"documents/builds/{build_id}/artifacts/{artifact_id}",
            max_bytes=_MAX_PDF_BYTES,
        )
        actual_digest = hashlib.sha256(content).hexdigest()
        header_digest = str(headers.get("x-artifact-sha256") or "").lower()
        if not content.startswith(b"%PDF-") or actual_digest != expected_digest:
            raise GigaChatSmokeFailure("artifact_integrity_invalid")
        if header_digest and header_digest != actual_digest:
            raise GigaChatSmokeFailure("artifact_integrity_invalid")
        usage = execution.usage.bounded_summary()
    return outcome, len(stages), len(content), usage["call_count"]


async def _run() -> None:
    if not _MODEL:
        raise GigaChatSmokeFailure("model_missing")
    await require_tool_model(_MODEL)
    ref = _read_private_fixture()
    cases = _cases()
    if not cases:
        raise GigaChatSmokeFailure("case_unknown")
    for case in cases:
        outcome, stage_count, pdf_bytes, model_calls = await _run_case(ref, case)
        print(
            "document authoring: provider=gigachat "
            f"model={_MODEL} case={case.name} outcome={outcome} stages={stage_count} "
            f"pdf_bytes={pdf_bytes} model_calls={model_calls}"
        )


if __name__ == "__main__":
    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - operational output must remain bounded
        print(f"document authoring smoke: FAILED code={bounded_failure_code(exc)}")
        raise SystemExit(1) from None
    print("document authoring smoke: OK")
