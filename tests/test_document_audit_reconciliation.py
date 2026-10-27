"""Artifact lifecycle does not establish that a prior producer's cost was settled."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application.documents.audit import reconciliation as reconcile
from service.services.chat.application.documents.publication import service as service
from service.services.chat.persistence.documents.audit.attempts import RecordedAuditResult


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["none", "sealed", "active", "already_settled"])
async def test_reconcile_only_settles_explicitly_resolved_attempt(monkeypatch, outcome):
    attempt = uuid4()
    ids = (
        [None]
        if outcome == "none"
        else [attempt, None if outcome == "already_settled" else attempt]
    )
    monkeypatch.setattr(reconcile, "started_id", AsyncMock(side_effect=ids))
    recorded = RecordedAuditResult({"total": 33}, "audit_failed") if outcome == "sealed" else None
    recovery = AsyncMock(return_value=recorded)
    settle = AsyncMock()
    monkeypatch.setattr(reconcile, "recover_started_result", recovery)
    result = await reconcile.reconcile_started_audit(
        object(),
        object(),
        object(),
        AsyncMock(),
        {"id": uuid4(), "user_id": uuid4(), "workspace_id": "fixture"},
        settle,
    )
    assert result is (outcome != "active")
    assert recovery.await_count == (0 if outcome == "none" else 1)
    assert settle.await_count == (1 if outcome in {"sealed", "already_settled"} else 0)
    if recovery.await_count:
        assert set(recovery.await_args.kwargs["ref"]) == {"user_id", "workspace_id"}


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["build", "saved", "expired"])
async def test_unresolved_audit_blocks_ready_saved_or_expired_shortcuts(monkeypatch, entry):
    events = []

    async def settled(**kwargs):
        events.append("pending_charge")

    async def unresolved(*args):
        events.append("reconcile")
        return False

    monkeypatch.setattr(service, "_settle_pending_audit", settled)
    monkeypatch.setattr(service, "reconcile_started_audit", unresolved)
    build = AsyncMock(return_value={"state": "ready"})
    saved = AsyncMock(return_value=uuid4() if entry == "saved" else None)
    binding = AsyncMock(return_value=None)
    terminal = AsyncMock()
    monkeypatch.setattr(service, "document_build_status", build)
    monkeypatch.setattr(service.document_publications, "saved_file_id", saved)
    monkeypatch.setattr(service, "read_binding", binding)
    monkeypatch.setattr(service, "_defer_terminal_publication", terminal)
    params = dict(
        config=object(),
        pg_connector=object(),
        redis=object(),
        session=AsyncMock(),
        row={"id": uuid4(), "lease_token": uuid4()},
    )
    if entry == "build":
        assert await service._ensure_audited_durable(**params, ref={}) == "unavailable"
    else:
        assert await service.deliver_one(**params, file_service=object()) == "deferred"
    assert events == ["pending_charge", "reconcile"]
    build.assert_not_awaited()
    saved.assert_not_awaited()
    binding.assert_not_awaited()
    terminal.assert_not_awaited()
