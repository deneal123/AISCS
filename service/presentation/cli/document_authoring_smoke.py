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
import re
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from service.domain.client.models.catalog import ModelCatalogSource
from service.domain.client.models.requirements import ModelRequirement
from service.domain.client.providers.management.admission import RunProviderAdmission
from service.domain.client.registry import initialize_run_provider_admission
from service.domain.documents.run_outcome import DOCUMENT_FAILURE_CODES, DocumentStage
from service.domain.documents.visual_audit import AUDIT_VERSION, MAX_PAGES
from service.domain.execution.context import (
    PrivateRunResources,
    RunExecutionContext,
    use_run_execution,
)
from service.domain.subagents.pdf_generation import PDFGenerationAgent
from service.domain.tools.workspace.client import call, download_binary
from service.domain.usage.ledger import UsageKind
from service.events import AgentEvent, EventType
from service.presentation.cli.gigachat.support import (
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
        "# Материалы обзорной статьи\n\n"
        "## Тема\n"
        "Надёжность систем генерации документов на основе больших языковых моделей.\n\n"
        "## Источник 1\n"
        "Lewis P. et al. Retrieval-Augmented Generation for Knowledge-Intensive NLP "
        "Tasks. NeurIPS 2020. DOI: 10.48550/arXiv.2005.11401\n"
        "https://arxiv.org/abs/2005.11401\n\n"
        "## Источник 2\n"
        "Ji Z. et al. Survey of Hallucination in Natural Language Generation. ACM "
        "Computing Surveys, 2023. DOI: 10.1145/3571730\n"
        "https://doi.org/10.1145/3571730\n\n"
        "## Требования\n"
        "Сравни подходы, опиши ограничения и сформулируй выводы. "
        "Не добавляй источники, отсутствующие в этих материалах.\n"
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
        required_stages.update({"deterministic_audit", "visual_audit"})
        waiting_audit = outcome == "deferred" and any(
            event.metadata.get("document_failure_code") == "visual_pending"
            for event in events
            if isinstance(event.metadata, dict)
        )
        # Visual-pending is a valid partial terminal, not a delivery attempt.
        # Readiness validation below still refuses to certify this build.
        if not waiting_audit:
            required_stages.add("delivery")
    if not required_stages.issubset(stages):
        raise GigaChatSmokeFailure("stage_contract_invalid")
    return outcome, stages


def _restrict_gigachat_scope(execution: RunExecutionContext) -> None:
    """Constrain every stage while retaining all generation leases for cleanup."""
    admission = execution.provider_admission
    if admission is None or execution.usage.receipts:
        raise GigaChatSmokeFailure("invalid_smoke_input")
    source = admission.snapshot
    if "gigachat" not in source.provider_order or source.client_for("gigachat") is None:
        raise GigaChatSmokeFailure("provider_unavailable")
    catalog = source.catalogs.get("gigachat")
    if (
        catalog is None
        or catalog.source is not ModelCatalogSource.LIVE
        or not catalog.discovery_available
        or not catalog.fresh
    ):
        raise GigaChatSmokeFailure("catalog_unavailable")
    scoped = replace(
        source,
        catalogs={"gigachat": catalog},
        records={"gigachat": source.records.get("gigachat", ())},
        clients={"gigachat": source.client_for("gigachat")},
        owner_index={
            model: owner for model, owner in source.owner_index.items() if owner == "gigachat"
        },
        provider_order=("gigachat",),
        active_provider="gigachat",
        generation_sequences={
            key: value for key, value in source.generation_sequences.items() if key == "gigachat"
        },
    )
    execution.provider_admission = RunProviderAdmission(scoped)

    def pick(models: list[str], _preferred: str | None) -> str | None:
        return models[0] if models else None

    author = execution.provider_admission.qualify(
        "gigachat", requirement=ModelRequirement(tools=True), prefer=_MODEL, pick_model=pick
    )
    if not author.compatible or author.model != _MODEL:
        raise GigaChatSmokeFailure("selected_model_unavailable")
    vision = execution.provider_admission.qualify(
        "gigachat",
        requirement=ModelRequirement(vision=True, tools=True),
        prefer=None,
        pick_model=pick,
    )
    if not vision.compatible:
        raise GigaChatSmokeFailure("no_compatible_model")


def _verify_gigachat_usage(execution: RunExecutionContext) -> None:
    for receipt in execution.usage.receipts:
        if receipt.provider != "gigachat" or not receipt.model:
            raise GigaChatSmokeFailure("provider_mismatch")
        if receipt.kind == UsageKind.PDF_AUTHORING and receipt.model != _MODEL:
            raise GigaChatSmokeFailure("model_mismatch")


def _assert_ready_status(status: Any) -> dict[str, Any]:
    """A paid vision receipt proves cost, not an accepted audit attestation."""
    if (
        not isinstance(status, dict)
        or status.get("state") != "ready"
        or status.get("final") is not True
        or status.get("failure_code") not in (None, "")
        or type(status.get("visual_audit_version")) is not int
        or status["visual_audit_version"] != AUDIT_VERSION
        or type(status.get("page_count")) is not int
        or not 1 <= status["page_count"] <= MAX_PAGES
        or not isinstance(status.get("source_revision"), str)
        or not status["source_revision"]
        or not isinstance(status.get("output_revision"), str)
        or not status["output_revision"]
    ):
        raise GigaChatSmokeFailure("document_not_ready")
    return status


def _print_stages(events: list[AgentEvent]) -> None:
    """Expose only closed stage labels, never event text or diagnostic payloads."""
    stages = frozenset(item.value for item in DocumentStage)
    statuses = frozenset(
        {"running", "ready", "empty", "pending", "failed", "queued", "draft_ready"}
    )
    count = 0
    for event in events:
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        status = metadata.get("document_status")
        if not isinstance(status, dict) or count >= 48:
            continue
        stage, state, failure = (status.get(key) for key in ("stage", "status", "failure_code"))
        stage = stage if type(stage) is str and stage in stages else "unknown"
        state = state if type(state) is str and state in statuses else "unknown"
        failure = failure if type(failure) is str and failure in DOCUMENT_FAILURE_CODES else "none"
        print(f"document stage: stage={stage} status={state} failure={failure}")
        count += 1


def _assert_artifact(status: dict[str, Any], artifact: dict[str, Any]) -> None:
    """Bind the result envelope to the exact registered, audited workspace PDF."""
    records = status.get("artifacts")
    pdfs = (
        [item for item in records if isinstance(item, dict) and item.get("role") == "pdf"]
        if isinstance(records, list)
        else []
    )
    if len(pdfs) != 1:
        raise GigaChatSmokeFailure("artifact_contract_invalid")
    pdf = pdfs[0]
    if (
        not isinstance(status.get("build_id"), str)
        or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", status["build_id"]) is None
        or artifact.get("build_id") != status["build_id"]
        or not isinstance(pdf.get("artifact_id"), str)
        or not pdf["artifact_id"]
        or artifact.get("artifact_id") != pdf["artifact_id"]
        or artifact.get("role") != "pdf"
        or pdf.get("mime_type") != "application/pdf"
        or artifact.get("mime_type") != "application/pdf"
        or type(pdf.get("size")) is not int
        or not 0 < pdf["size"] <= _MAX_PDF_BYTES
        or type(artifact.get("size")) is not int
        or artifact["size"] != pdf["size"]
        or not isinstance(pdf.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", pdf["sha256"]) is None
        or artifact.get("sha256") != pdf["sha256"]
        or not isinstance(status.get("source_digest"), str)
        or re.fullmatch(r"[0-9a-f]{64}", status["source_digest"]) is None
        or artifact.get("source_digest") != status["source_digest"]
    ):
        raise GigaChatSmokeFailure("artifact_contract_invalid")


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
        _restrict_gigachat_scope(execution)
        agent = _SmokeAgent({"model": _MODEL})
        try:
            events = [
                event
                async for event in agent.process(
                    case.request,
                    context,
                )
            ]
        finally:
            _verify_gigachat_usage(execution)
            usage = execution.usage.bounded_summary()
            print(
                "document usage: provider=gigachat "
                f"model_calls={usage['call_count']} "
                f"billable_calls={usage['billable_call_count']} "
                f"prompt_tokens={usage['prompt_tokens']} "
                f"completion_tokens={usage['completion_tokens']}"
            )
        _print_stages(events)
        outcome, stages = _assert_terminal(
            events,
            expect_semantic_authoring=not case.name.startswith("literal"),
        )
        if outcome not in {"completed", "deferred"}:
            status = agent.final_status or {}
            diagnostics = status.get("diagnostics")
            diagnostic_count = (
                len(diagnostics) if isinstance(diagnostics, (dict, list, tuple)) else 0
            )
            print(
                "document terminal: "
                "status=not_ready "
                f"model_calls={execution.usage.bounded_summary()['call_count']} "
                f"diagnostic_count={min(diagnostic_count, 999)}"
            )
            raise GigaChatSmokeFailure("document_not_ready")
        if not execution.usage.has_kind(UsageKind.DOCUMENT_VISUAL_AUDIT):
            raise GigaChatSmokeFailure("usage_missing")
        status = _assert_ready_status(agent.final_status)
        artifact = _artifact(events)
        _assert_artifact(status, artifact)
        build_id = str(artifact.get("build_id") or "")
        artifact_id = str(artifact.get("artifact_id") or "")
        expected_digest = str(artifact.get("sha256") or "").lower()
        if not build_id or not artifact_id or len(expected_digest) != 64:
            raise GigaChatSmokeFailure("artifact_contract_invalid")
        # A stale agent result cannot certify a cancelled/replaced build. This is
        # one read only: no recompile, audit retry, publication or model call.
        confirmed = _assert_ready_status(await call(ref, f"documents/builds/{build_id}", {}))
        _assert_artifact(confirmed, artifact)
        content, headers = await download_binary(
            ref,
            f"documents/builds/{build_id}/artifacts/{artifact_id}",
            max_bytes=_MAX_PDF_BYTES,
        )
        actual_digest = hashlib.sha256(content).hexdigest()
        header_digest = str(headers.get("x-artifact-sha256") or "").lower()
        if (
            not content.startswith(b"%PDF-")
            or actual_digest != expected_digest
            or len(content) != artifact["size"]
        ):
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
    print("document authoring smoke: OK scope=audited_workspace_pdf delivery=not_checked")
