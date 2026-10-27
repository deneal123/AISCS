"""GigaChat certification must constrain calls, not merely print a provider label."""

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.domain.client.models.catalog import (
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.providers.management.admission import (
    RunProviderAdmission,
    RunProviderSnapshot,
)
from service.domain.documents.run_outcome import (
    DocumentRunOutcome,
    DocumentStage,
    document_status_event,
)
from service.domain.execution.context import require_current_execution, use_run_execution
from service.domain.usage.ledger import UsageReceipt
from service.events import AgentEvent, EventType
from service.presentation.cli import document_authoring_smoke as smoke
from service.presentation.cli.gigachat.support import GigaChatSmokeFailure


def snapshot(*, giga_vision=True, giga_allowed=True):
    records = {
        "gigachat": (
            ProviderModelRecord(
                smoke._MODEL, frozenset({"chat", "tools", *({"vision"} if giga_vision else set())})
            ),
        ),
        "openai": (ProviderModelRecord("foreign", frozenset({"chat", "tools", "vision"})),),
    }
    catalogs = {
        provider: ProviderModelCatalog(
            provider,
            tuple(item.model_id for item in items),
            ModelCatalogSource.LIVE,
            ModelCatalogStatus.AVAILABLE,
            True,
            items,
        )
        for provider, items in records.items()
    }
    return RunProviderSnapshot(
        catalogs=catalogs,
        records=records,
        clients={key: object() for key in records},
        owner_index={smoke._MODEL: "gigachat", "foreign": "openai"},
        provider_order=("gigachat", "openai") if giga_allowed else ("openai",),
        active_provider="openai",
        configuration_generation="synthetic",
    )


def fixture(monkeypatch, *, giga_vision=True, giga_allowed=True, receipt_provider="gigachat"):
    original = snapshot(giga_vision=giga_vision, giga_allowed=giga_allowed)
    calls = []
    pdf = b"%PDF-synthetic"
    digest = hashlib.sha256(pdf).hexdigest()
    artifact = {
        "build_id": "build",
        "artifact_id": "artifact",
        "role": "pdf",
        "sha256": digest,
        "source_digest": "a" * 64,
        "size": len(pdf),
        "mime_type": "application/pdf",
    }
    status = {
        "build_id": "build",
        "state": "ready",
        "final": True,
        "failure_code": None,
        "visual_audit_version": 1,
        "page_count": 1,
        "source_digest": "a" * 64,
        "source_revision": "source-r1",
        "output_revision": "output-r1",
        "artifacts": [artifact],
    }

    async def initialize(execution):
        execution.provider_admission = RunProviderAdmission(original)
        return execution.provider_admission

    class Agent:
        final_status = status

        def __init__(self, *_):
            pass

        async def process(self, *_):
            execution = require_current_execution()
            calls.append(execution.provider_snapshot)
            execution.usage.record(
                UsageReceipt(
                    "synthetic-call",
                    receipt_provider,
                    smoke._MODEL,
                    1,
                    1,
                    kind="document_visual_audit",
                )
            )
            if False:
                yield None

    monkeypatch.setattr(smoke, "initialize_run_provider_admission", initialize)
    monkeypatch.setattr(smoke, "_SmokeAgent", Agent)
    monkeypatch.setattr(smoke, "_assert_terminal", lambda *_, **__: ("completed", set()))
    monkeypatch.setattr(
        smoke,
        "_artifact",
        lambda _: dict(artifact),
    )
    monkeypatch.setattr(smoke, "call", AsyncMock(return_value=status), raising=False)
    download = AsyncMock(return_value=(pdf, {}))
    monkeypatch.setattr(smoke, "download_binary", download)
    ref = {"user_id": "synthetic", "workspace_id": "workspace", "token": "private"}
    return original, calls, download, ref


@pytest.mark.asyncio
async def test_all_stages_see_only_gigachat_without_mutating_original(monkeypatch):
    original, calls, _, ref = fixture(monkeypatch)
    await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    scoped = calls[0]
    assert scoped.provider_order == ("gigachat",)
    assert set(scoped.clients) == set(scoped.catalogs) == {"gigachat"}
    assert scoped.owner_for("foreign") is None
    assert original.provider_order == ("gigachat", "openai")
    assert original.owner_for("foreign") == "openai"


@pytest.mark.asyncio
async def test_missing_gigachat_vision_stops_before_agent_or_download(monkeypatch):
    _, calls, download, ref = fixture(monkeypatch, giga_vision=False)
    with pytest.raises(GigaChatSmokeFailure, match="^no_compatible_model$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    assert not calls
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_policy_cannot_be_bypassed_by_smoke(monkeypatch):
    _, calls, download, ref = fixture(monkeypatch, giga_allowed=False)
    with pytest.raises(GigaChatSmokeFailure, match="^provider_unavailable$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    assert not calls
    download.assert_not_awaited()


@pytest.mark.parametrize("provider", ["openai", None])
@pytest.mark.asyncio
async def test_foreign_or_missing_receipt_provenance_cannot_be_certified(monkeypatch, provider):
    _, _, download, ref = fixture(monkeypatch, receipt_provider=provider)
    with pytest.raises(GigaChatSmokeFailure, match="^provider_mismatch$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()


def test_scoped_filter_retains_all_generation_leases_for_single_cleanup():
    giga, foreign = Mock(), Mock()
    with use_run_execution(smoke.PrivateRunResources()) as execution:
        original = replace(snapshot(), leases=(giga, foreign))
        execution.provider_admission = RunProviderAdmission(original)
        smoke._restrict_gigachat_scope(execution)
        assert execution.provider_snapshot.leases == (giga, foreign)
        assert original.clients.get("openai") is not None
    giga.release.assert_called_once()
    foreign.release.assert_called_once()


@pytest.mark.parametrize(
    ("source", "status", "fresh"),
    [
        (ModelCatalogSource.STATIC_FALLBACK, ModelCatalogStatus.AVAILABLE, True),
        (ModelCatalogSource.STALE, ModelCatalogStatus.AVAILABLE, False),
        (ModelCatalogSource.LIVE, ModelCatalogStatus.AUTH, True),
        (ModelCatalogSource.LIVE, ModelCatalogStatus.AVAILABLE, False),
    ],
)
def test_nonlive_or_unavailable_catalog_cannot_be_certified(source, status, fresh):
    with use_run_execution(smoke.PrivateRunResources()) as execution:
        original = snapshot()
        catalog = replace(original.catalogs["gigachat"], source=source, status=status, fresh=fresh)
        execution.provider_admission = RunProviderAdmission(
            replace(original, catalogs={**original.catalogs, "gigachat": catalog})
        )
        with pytest.raises(GigaChatSmokeFailure, match="^catalog_unavailable$"):
            smoke._restrict_gigachat_scope(execution)


def test_scope_cannot_be_replaced_after_an_accepted_call():
    with use_run_execution(smoke.PrivateRunResources()) as execution:
        original = RunProviderAdmission(snapshot())
        execution.provider_admission = original
        execution.usage.record(UsageReceipt("accepted", "gigachat", smoke._MODEL, 1, 1))
        with pytest.raises(GigaChatSmokeFailure, match="^invalid_smoke_input$"):
            smoke._restrict_gigachat_scope(execution)
        assert execution.provider_admission is original
        assert len(execution.usage.receipts) == 1


@pytest.mark.asyncio
async def test_failure_summary_does_not_print_status_or_diagnostic_payload(monkeypatch, capsys):
    _, _, download, ref = fixture(monkeypatch)
    base = smoke._SmokeAgent

    class FailedAgent(base):
        final_status = {
            "stage": "PRIVATE_STAGE",
            "failure_code": "PRIVATE_BODY",
            "authoring_rejection_reason": "PRIVATE_QUERY",
            "diagnostics": [{"code": "PRIVATE_DIAGNOSTIC"}],
        }

    monkeypatch.setattr(smoke, "_SmokeAgent", FailedAgent)
    monkeypatch.setattr(smoke, "_assert_terminal", lambda *_, **__: ("failed", set()))
    with pytest.raises(GigaChatSmokeFailure, match="^document_not_ready$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    assert "PRIVATE" not in capsys.readouterr().out
    download.assert_not_awaited()


def test_authoring_receipt_must_keep_exact_selected_model():
    with use_run_execution(smoke.PrivateRunResources()) as execution:
        execution.usage.record(
            UsageReceipt("wrong-author", "gigachat", "different", 1, 1, kind="pdf_authoring")
        )
        with pytest.raises(GigaChatSmokeFailure, match="^model_mismatch$"):
            smoke._verify_gigachat_usage(execution)


@pytest.mark.asyncio
async def test_completed_metadata_without_actual_visual_receipt_is_not_proof(monkeypatch):
    _, _, download, ref = fixture(monkeypatch)
    base = smoke._SmokeAgent

    class NoVisualAgent(base):
        async def process(self, *_):
            execution = require_current_execution()
            execution.usage.record(
                UsageReceipt("only-author", "gigachat", smoke._MODEL, 1, 1, kind="pdf_authoring")
            )
            if False:
                yield None

    monkeypatch.setattr(smoke, "_SmokeAgent", NoVisualAgent)
    with pytest.raises(GigaChatSmokeFailure, match="^usage_missing$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "visual_pending"},
        {"state": "failed", "failure_code": "visual_audit_failed"},
        {"visual_audit_version": 0},
        {"visual_audit_version": True},
        {"final": False},
        {"failure_code": "PRIVATE_PROVIDER_BODY"},
        {"page_count": 0},
        {"failure_code": {"body": "PRIVATE_PROVIDER_BODY"}},
        {"source_revision": ""},
    ],
)
@pytest.mark.asyncio
async def test_visual_receipt_and_deferred_outcome_do_not_prove_ready(monkeypatch, changes, capsys):
    _, _, download, ref = fixture(monkeypatch)
    smoke._SmokeAgent.final_status = {**smoke._SmokeAgent.final_status, **changes}
    monkeypatch.setattr(smoke, "_assert_terminal", lambda *_, **__: ("deferred", set()))
    with pytest.raises(GigaChatSmokeFailure, match="^document_not_ready$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_canonical_status_must_still_confirm_exact_audited_build(monkeypatch):
    _, _, download, ref = fixture(monkeypatch)
    smoke.call.return_value = {**smoke._SmokeAgent.final_status, "state": "cancelled"}
    with pytest.raises(GigaChatSmokeFailure, match="^document_not_ready$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()


@pytest.mark.parametrize("field", ["build_id", "source_digest", "artifact_id", "sha256"])
@pytest.mark.asyncio
async def test_unrelated_artifact_cannot_certify_a_ready_build(monkeypatch, field):
    _, _, download, ref = fixture(monkeypatch)
    original = smoke._artifact([])
    monkeypatch.setattr(smoke, "_artifact", lambda _: {**original, field: "PRIVATE_FOREIGN"})
    with pytest.raises(GigaChatSmokeFailure, match="^artifact_contract_invalid$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_actual_pdf_size_must_match_registered_artifact(monkeypatch):
    _, _, _, ref = fixture(monkeypatch)
    smoke._SmokeAgent.final_status["artifacts"][0]["size"] += 1
    with pytest.raises(GigaChatSmokeFailure, match="^artifact_integrity_invalid$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))


@pytest.mark.asyncio
async def test_duplicate_registered_pdf_is_not_an_exact_artifact_match(monkeypatch):
    _, _, download, ref = fixture(monkeypatch)
    status = smoke._SmokeAgent.final_status
    status["artifacts"] = [*status["artifacts"], dict(status["artifacts"][0])]
    with pytest.raises(GigaChatSmokeFailure, match="^artifact_contract_invalid$"):
        await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    download.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_delivery_with_confirmed_ready_pdf_is_valid_workspace_evidence(monkeypatch):
    _, calls, download, ref = fixture(monkeypatch)
    monkeypatch.setattr(smoke, "_assert_terminal", lambda *_, **__: ("deferred", set()))
    outcome, _, _, receipts = await smoke._run_case(ref, smoke._Case("literal", smoke._REQUEST))
    assert outcome == "deferred"
    assert receipts == len(calls) == 1
    smoke.call.assert_awaited_once_with(ref, "documents/builds/build", {})
    download.assert_awaited_once()


def test_stage_diagnostics_have_closed_labels_and_no_raw_payload(capsys):
    events = [
        SimpleNamespace(
            metadata={
                "document_status": {
                    "stage": "visual_audit",
                    "status": "pending",
                    "failure_code": "visual_pending",
                    "body": "PRIVATE_TRANSCRIPT",
                    "url": "PRIVATE_URL",
                }
            }
        ),
        SimpleNamespace(
            metadata={
                "document_status": {
                    "stage": "PRIVATE_STAGE",
                    "status": {"PRIVATE_BODY": True},
                    "failure_code": "PRIVATE_PROVIDER_RESPONSE",
                }
            }
        ),
    ]
    smoke._print_stages(events)
    output = capsys.readouterr().out
    assert "stage=visual_audit status=pending failure=visual_pending" in output
    assert "stage=unknown status=unknown failure=none" in output
    assert "PRIVATE" not in output


def test_visual_pending_terminal_does_not_fabricate_a_delivery_stage():
    stages = [
        DocumentStage.INTENT,
        DocumentStage.EVIDENCE,
        DocumentStage.SOURCE_PUBLISH,
        DocumentStage.COMPILE,
        DocumentStage.DETERMINISTIC_AUDIT,
    ]
    events = [document_status_event("pdf_gen", stage, "ready") for stage in stages]
    events.append(
        document_status_event(
            "pdf_gen",
            DocumentStage.VISUAL_AUDIT,
            "pending",
            outcome=DocumentRunOutcome.DEFERRED,
            failure_code="visual_pending",
            retryable=True,
        )
    )
    events.append(
        AgentEvent(
            type=EventType.AGENT_COMPLETE,
            agent_name="pdf_gen",
            metadata={
                "requested_authoring_model": smoke._MODEL,
                "actual_authoring_model": smoke._MODEL,
                "document_outcome": "deferred",
            },
        )
    )
    outcome, recorded_stages = smoke._assert_terminal(events, expect_semantic_authoring=False)
    assert outcome == "deferred"
    assert "delivery" not in recorded_stages
