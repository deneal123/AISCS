"""Совместимый replay возвращает исходную оплаченную операцию, не новый grant."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness import grants
from service.services.chat.persistence.harness.model_replay import completed_step_replay
from service.shared.harness_protocol import CallReceipt, HarnessFailure
from service.shared.task_contract import digest_payload
from tests.test_harness_frozen_model_request import request, row
from tests.test_harness_runtime_contract import admission


def frame():
    function = {"name": "ide_read_file", "parameters": {"type": "object", "properties": {}}}
    body = {
        "messages": [{"role": "user", "content": "Прочитай файл"}],
        "tools": [{"type": "function", "function": function}],
        "tool_choice": "auto",
        "temperature": 0.1,
        "max_tokens": 10,
    }
    call = request(body=body)
    receipt = CallReceipt(
        operation_id=call.operation_id,
        status="succeeded",
        prompt=12,
        completion=2,
        provider_state={"provider": "gigachat", "model": "test", "state_id": "PRIVATE_STATE"},
        message={
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read",
                    "type": "function",
                    "function": {"name": "ide_read_file", "arguments": "{}"},
                }
            ],
        },
    ).model_dump(mode="json")
    record = {
        "state": "succeeded",
        "request": call.model_dump(mode="json"),
        "request_digest": digest_payload(call.model_dump(mode="json")),
        "receipt": receipt,
    }
    return body, call, record, {**row(), "tariff": {}}


@pytest.mark.parametrize(
    "change",
    [
        {"temperature": 0.8},
        {"max_tokens": 1},
        {"seed": 123},
        {"top_p": 0.5},
    ],
)
def test_sampling_drift_reuses_original_receipt_without_changing_it(change):
    body, original, saved, current = frame()
    before = deepcopy(saved)
    result = completed_step_replay(current, request(body={**body, **change}), [saved])
    assert result["operation_id"] == original.operation_id
    assert result["receipt"] == before["receipt"] and saved == before


def test_adding_unused_tool_preserves_the_already_obtained_call():
    body, original, saved, current = frame()
    changed = deepcopy(body)
    changed["tools"].append({"type": "function", "function": {"name": "ide_list_files"}})
    assert (
        completed_step_replay(current, request(body=changed), [saved])["operation_id"]
        == original.operation_id
    )


@pytest.mark.parametrize("change", ["arguments", "removed", "choice", "format", "messages"])
def test_semantic_drift_does_not_consume_an_incompatible_tool_call(change):
    body, _, saved, current = frame()
    if change == "arguments":
        body["tools"][0]["function"]["parameters"]["required"] = ["new_required"]
    elif change == "removed":
        body["tools"] = []
    elif change == "choice":
        body["tool_choice"] = "none"
    elif change == "format":
        body["response_format"] = {"type": "json_object"}
    else:
        body["messages"][0]["content"] = "Иная задача"
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        completed_step_replay(current, request(body=body), [saved])


@pytest.mark.parametrize("state", ["allocated", "dispatched", "unknown"])
def test_unknown_or_unfinished_provider_result_is_not_replayed(state):
    body, _, saved, current = frame()
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        completed_step_replay(current, request(body=body), [{**saved, "state": state}])


@pytest.mark.parametrize(
    "change",
    [
        {"estimated": True},
        {"message": None},
        {"operation_id": str(uuid4())},
        {"provider_state": None},
        {"prompt": 0, "completion": 0},
        {"provider_state": {"provider": "openai", "model": "test", "state_id": "PRIVATE_OTHER"}},
    ],
)
def test_corrupt_receipt_does_not_become_a_replay(change):
    body, _, saved, current = frame()
    saved["receipt"].update(change)
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        completed_step_replay(current, request(body=body), [saved])


@pytest.mark.asyncio
async def test_replay_path_never_inserts_another_grant(monkeypatch):
    body, original, saved, current = frame()
    current.update(admission=admission().model_dump(mode="json"), task_id=uuid4())
    monkeypatch.setattr(grants, "_read", AsyncMock(return_value=None))
    monkeypatch.setattr(grants, "grant_rows", AsyncMock(return_value=[saved]))
    db = SimpleNamespace(execute=AsyncMock())
    result = await grants.allocate(db, current, request(body={**body, "temperature": 0.9}))
    assert result["operation_id"] == original.operation_id
    db.execute.assert_not_awaited()
