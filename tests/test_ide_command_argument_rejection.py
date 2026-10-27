"""A schema refusal can close only an exact locked intent with no executor record."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.commands import validation
from service.shared.harness_protocol import HarnessFailure


def setup(monkeypatch, *, actual=None, command=None):
    arguments = {"profile": "python_script", "target": "hello.py", "command": "python hello.py"}
    intent = {"name": "ide_run_command", "action": "exec", "arguments": json.dumps(arguments)}
    record = {"intent": intent, "status": "dispatched", "command": command}
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=Mock(
                mappings=Mock(return_value=Mock(first=Mock(return_value=record))),
            )
        )
    )
    monkeypatch.setattr(validation, "owned_row", AsyncMock(return_value={"task_id": uuid4()}))
    monkeypatch.setattr(validation, "snapshot", AsyncMock(return_value=object()))
    saved = AsyncMock(return_value={"status": "failed"})
    monkeypatch.setattr(validation.effects, "record", saved)
    return db, arguments if actual is None else actual, saved


@pytest.mark.asyncio
async def test_exact_invalid_arguments_are_known_no_effect_not_unknown(monkeypatch):
    db, args, saved = setup(monkeypatch)
    await validation.reject_invalid(db, object(), uuid4(), args)
    receipt = saved.await_args.args[2]
    assert receipt.status == "failed" and not receipt.charged and not receipt.evidence
    assert receipt.text == "ide_command_arguments_rejected"


@pytest.mark.asyncio
async def test_existing_executor_record_forbids_a_preexecution_refusal(monkeypatch):
    db, args, saved = setup(monkeypatch, command={"state": "unknown"})
    with pytest.raises(HarnessFailure, match="operation_unknown"):
        await validation.reject_invalid(db, object(), uuid4(), args)
    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_wire_arguments_cannot_retire_someone_elses_intent(monkeypatch):
    db, args, saved = setup(monkeypatch, actual={"profile": "python_script", "target": "b.py"})
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await validation.reject_invalid(db, object(), uuid4(), args)
    saved.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_canonical_recipe_cannot_be_declared_a_known_failure(monkeypatch):
    db, _, saved = setup(monkeypatch)
    arguments = {"profile": "python_script", "target": "a.py"}
    record = db.execute.return_value.mappings.return_value.first.return_value
    record["intent"]["arguments"] = json.dumps(arguments)
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await validation.reject_invalid(db, object(), uuid4(), arguments)
    saved.assert_not_awaited()
