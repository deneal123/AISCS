"""A previously admitted intent cannot bypass later uncertainty or a disabled surface.

These are offline transaction-body checks, not PostgreSQL concurrency acceptance.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application import harness_capability
from service.services.chat.application.harness_capability import HarnessSettings, require_dispatch
from service.services.chat.persistence.harness import effects as harness_effects
from service.services.chat.persistence.harness import grants as harness_grants
from service.services.chat.persistence.harness import runtime as harness_runtime
from service.shared.harness_protocol import Exchange, HarnessFailure, Snapshot
from tests.test_harness_runtime_contract import admission


@pytest.mark.parametrize("surface", ["ide", "pdf"])
@pytest.mark.parametrize("enabled", [False, True])
def test_surface_flag_gates_dispatch(monkeypatch, surface, enabled):
    flags = HarnessSettings(ide_enabled=False, pdf_enabled=False)
    flags = flags.model_copy(update={surface + "_enabled": enabled})
    monkeypatch.setattr(harness_capability, "settings", lambda: flags)
    current = admission().model_copy(update={"surface": surface})
    if enabled:
        require_dispatch(current)
    else:
        with pytest.raises(HarnessFailure, match="dispatch_disabled"):
            require_dispatch(current)


@pytest.mark.asyncio
async def test_allocated_grant_cannot_dispatch_after_another_cost_becomes_unknown(monkeypatch):
    monkeypatch.setattr(harness_grants, "settings", lambda: SimpleNamespace(dispatch_enabled=True))
    monkeypatch.setattr(harness_grants, "_read", AsyncMock(return_value={"state": "allocated"}))
    db = SimpleNamespace(scalar=AsyncMock(return_value=True), execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="cost_unknown"):
        await harness_grants.dispatch(db, {"task_id": uuid4()}, str(uuid4()))
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_cost", [False, True])
async def test_prepared_effect_rechecks_both_cost_and_other_effects(monkeypatch, unknown_cost):
    monkeypatch.setattr(harness_effects, "read", AsyncMock(return_value={"status": "prepared"}))
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[True] if unknown_cost else [False, True]),
        execute=AsyncMock(),
    )
    code = "cost_unknown" if unknown_cost else "operation_unknown"
    with pytest.raises(HarnessFailure, match=code):
        await harness_effects.dispatch(db, {"task_id": uuid4()}, str(uuid4()))
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", [harness_grants.dispatch, harness_effects.dispatch])
async def test_acknowledged_dispatch_is_not_authorized_again(monkeypatch, dispatch):
    if dispatch is harness_grants.dispatch:
        monkeypatch.setattr(
            harness_grants, "settings", lambda: SimpleNamespace(dispatch_enabled=True)
        )
        monkeypatch.setattr(
            harness_grants, "_read", AsyncMock(return_value={"state": "dispatched"})
        )
    else:
        monkeypatch.setattr(
            harness_effects, "read", AsyncMock(return_value={"status": "dispatched"})
        )
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock())
    result = await dispatch(db, {"task_id": uuid4()}, str(uuid4()))
    assert result == {"status": "dispatched", "dispatch_allowed": False}
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_surface_preserves_receipt_recording_and_result_reads(monkeypatch):
    row = {"revision": 0, "task_id": uuid4()}
    current = Snapshot(admission=admission())
    monkeypatch.setattr(harness_runtime, "owned_row", AsyncMock(return_value=row))
    monkeypatch.setattr(harness_runtime, "snapshot", AsyncMock(return_value=current))
    monkeypatch.setattr(harness_capability, "settings", lambda: HarnessSettings())
    record = AsyncMock(return_value={"status": "succeeded"})
    monkeypatch.setattr(harness_grants, "record", record)
    repo = harness_runtime.HarnessRuntimeRepository(None)
    db = SimpleNamespace(scalar=AsyncMock(return_value=False))

    async def transaction(body):
        return await body(db)

    monkeypatch.setattr(repo, "_transaction", transaction)
    request = Exchange(
        opcode="call_receipt",
        receipt={"operation_id": str(uuid4()), "status": "unknown"},
    )
    assert (await repo.exchange(None, request))["operation"]["status"] == "succeeded"
    record.assert_awaited_once()
    assert (await repo.exchange(None, Exchange(opcode="result")))["result"] is None
