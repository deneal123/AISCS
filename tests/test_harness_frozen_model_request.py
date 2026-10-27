"""Изменение запроса на том же шаге не создаёт второй платный grant."""

import json
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.model_requests import (
    matching_request,
    require_codec_transition,
    require_frozen_request,
    require_unique_step,
)
from service.shared.harness_protocol import Continuation, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload


def request(*, body=None, **change):
    payload = body or {"messages": [{"role": "user", "content": "Прочитай файл"}]}
    return PaidCall.model_validate(
        {
            "operation_id": str(uuid4()),
            "provider": "gigachat",
            "model": "test",
            "prompt": 2000,
            "completion": 10,
            "request_digest": digest_payload(payload),
            "canonical_request": json.dumps(payload),
            "continuation_step": 3,
            **change,
        }
    )


def row(**change):
    return {
        "continuation": {
            "phase": "model",
            "next_step": 3,
            "call_payload_version": 2,
            "provider": {"provider": "gigachat", "model": "test"},
            "messages": [{"role": "user", "content": "Прочитай файл"}],
            **change,
        }
    }


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"temperature": 0.2},
        {"tools": [{"type": "function", "function": {"name": "new"}}]},
    ],
)
@pytest.mark.parametrize("state", ["allocated", "dispatched", "succeeded", "unknown"])
def test_other_operation_for_the_same_step_is_blocked_in_every_state(change, state):
    original = request()
    candidate = request(body={"messages": [{"role": "user", "content": "Прочитай файл"}], **change})
    require_frozen_request(row(), candidate)
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_unique_step(candidate, [{"request": original.model_dump(), "state": state}])


@pytest.mark.parametrize(
    "change",
    [
        {"next_step": 4},
        {"phase": "tools"},
        {"call_payload_version": 1},
        {"provider": {"provider": "openai", "model": "test"}},
    ],
)
def test_request_cannot_change_its_backend_owned_execution_step(change):
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_frozen_request(row(**change), request())


@pytest.mark.parametrize(
    "change",
    [
        {"canonical_request": None},
        {"canonical_request": "PRIVATE_INVALID_JSON"},
        {"continuation_step": None},
        {"request_digest": "f" * 64},
        {"billing_tool": "workspace_tool"},
        {"prompt": 1},
    ],
)
def test_missing_corrupted_or_tool_owned_request_does_not_get_model_slot(change):
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_frozen_request(row(), request(**change))


def test_secret_bearing_settings_are_not_persisted_as_model_body():
    call = request(body={"messages": [], "headers": {"Authorization": "PRIVATE_TOKEN"}})
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_frozen_request(row(messages=[]), call)
    assert "PRIVATE_TOKEN" not in repr(call)


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [], "model": "other"},
        {"messages": [], "max_tokens": 11},
        {"messages": [], "max_tokens": True},
        {"messages": [], "max_completion_tokens": -1},
    ],
)
def test_frozen_body_cannot_exceed_granted_model_or_token_limits(body):
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_frozen_request(row(messages=body["messages"]), request(body=body))


def test_old_grant_can_be_read_without_rewriting_its_original_digest():
    old = request(continuation_step=None, canonical_request=None).model_dump(mode="json")
    old.pop("continuation_step")
    old.pop("canonical_request")
    stored = {"request": old, "request_digest": digest_payload(old)}
    assert matching_request(stored, PaidCall.model_validate(old))
    assert not matching_request(
        {**stored, "request_digest": "f" * 64}, PaidCall.model_validate(old)
    )


def test_other_step_and_tool_surcharges_do_not_occupy_model_slot():
    previous = request(continuation_step=2).model_dump()
    fee = request(billing_tool="workspace_tool").model_dump()
    require_unique_step(request(), [{"request": previous}, {"request": fee}])


def test_gigachat_legacy_function_dialect_remains_a_supported_frozen_body():
    call = request(
        body={
            "messages": [],
            "functions": [{"name": "submit_task_contract", "parameters": {"type": "object"}}],
            "function_call": {"name": "submit_task_contract"},
        }
    )
    require_frozen_request(row(messages=[]), call)


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_provider_adapters_share_binding_and_slot_rules(provider):
    call = request(provider=provider)
    current = row(provider={"provider": provider, "model": "test"})
    require_frozen_request(current, call)
    require_unique_step(call, [])
    with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
        require_unique_step(call, [{"request": call.model_dump()}])


@pytest.mark.parametrize(
    "old_version,new_version,messages,allowed",
    [
        (0, 2, [], True),
        (2, 2, [], True),
        (2, 1, [], False),
        (1, 2, [{"role": "user", "content": "Прежняя задача"}], False),
        (0, 2, [{"role": "user", "content": "Прежняя задача"}], False),
    ],
)
def test_backend_cannot_silently_upgrade_legacy_or_downgrade_frozen_codec(
    old_version, new_version, messages, allowed
):
    old = Continuation(call_payload_version=old_version, messages=messages)
    new = old.model_copy(update={"call_payload_version": new_version})
    if allowed:
        require_codec_transition(old, new)
    else:
        with pytest.raises(HarnessFailure, match="provider_state_incompatible"):
            require_codec_transition(old, new)
