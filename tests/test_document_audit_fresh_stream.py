"""Fresh worker permission, commit ordering, lease checks and uncertain completion."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.agents_client.document_audit import client as client
from service.infrastructure.sidecar import SidecarClient, SidecarUnavailable
from service.services.chat.application.documents.audit import invocation as invocation
from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


@pytest.mark.asyncio
async def test_fresh_invocation_checks_lease_and_commits_before_accepting_completion(monkeypatch):
    events = []
    attempt = uuid4()
    row = {"build_id": "fixture-build"}

    async def before():
        events.append("lease")

    async def stage(session, *, row, payload):
        events.append("checkpoint")

    monkeypatch.setattr(invocation, "stage_checkpoint", stage)
    session = SimpleNamespace(commit=AsyncMock(side_effect=lambda: events.append("commit")))

    async def audit(config, **kwargs):
        events.append("request")
        assert kwargs["checkpoint_attempt_id"] == attempt and kwargs["fresh_attempt"] is True
        await kwargs["checkpoint_sink"]({"fixture": True})
        events.append("terminal")
        return {"passed": False}

    await invocation.invoke_fresh_audit(object(), session, row, {}, attempt, audit, before)
    assert events == ["lease", "request", "lease", "checkpoint", "commit", "terminal"]


@pytest.mark.asyncio
async def test_stream_transport_failure_is_unresolved_not_an_empty_terminal(monkeypatch):
    monkeypatch.setattr(client.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(client.provider_policy, "blocked_providers", AsyncMock(return_value=()))

    async def broken(*args, **kwargs):
        raise SidecarUnavailable("agents", "transport")
        yield

    monkeypatch.setattr(SidecarClient, "request_ndjson", broken)
    result = await client.audit_document(
        object(),
        workspace_ref={},
        build_id="fixture-build",
        checkpoint_attempt_id=uuid4(),
        checkpoint_sink=AsyncMock(),
        fresh_attempt=True,
    )
    assert result["producer_unresolved"] is True and not result["passed"]


@pytest.mark.asyncio
async def test_uncertain_fresh_producer_never_records_or_charges_empty_result(monkeypatch):
    row = {
        "id": uuid4(),
        "build_id": "fixture-build",
        "source_digest": "a" * 64,
        "artifact_id": "fixture",
        "artifact_sha256": "b" * 64,
        "artifact_size": 1,
        "mime_type": "application/pdf",
    }
    status = {
        "state": "visual_pending",
        "build_id": row["build_id"],
        "source_digest": row["source_digest"],
        "artifacts": [
            {
                "artifact_id": "fixture",
                "sha256": "b" * 64,
                "size": 1,
                "mime_type": "application/pdf",
            }
        ],
    }
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    monkeypatch.setattr(
        service.document_audit_attempts, "attestation_pending", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(
            return_value={
                "id": uuid4(),
                "state": "started",
                "may_execute": True,
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "audit_document",
        AsyncMock(
            return_value={
                "status": "unavailable",
                "passed": False,
                "retryable": True,
                "producer_unresolved": True,
            }
        ),
    )
    record, charge, settle = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(service.document_audit_attempts, "record_merged_result", record)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    assert (
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=AsyncMock(),
            ref={},
            row=row,
        )
        == "unavailable"
    )
    record.assert_not_awaited()
    charge.assert_not_awaited()
    settle.assert_not_awaited()
