"""Приёмка отличает реальный alias исходного receipt от обычного grant/replay."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.harness.live.replay import observe_replay
from tests.test_harness_completed_model_replay import frame


def observation():
    _, _, saved, _ = frame()
    receipt = saved["receipt"]
    fault = SimpleNamespace(boundary={"receipt": receipt}, replayed_grants=[])
    payload = {
        "opcode": "grant",
        "call": {
            "operation_id": str(uuid4()),
            "canonical_request": json.dumps({"max_tokens": 128}),
        },
    }
    response = {
        "operation": {
            "status": "succeeded",
            "operation_id": receipt["operation_id"],
            "receipt": receipt,
        }
    }
    return fault, payload, response


def test_observation_requires_original_receipt_and_changed_tuning():
    fault, payload, response = observation()
    observe_replay(fault, payload, response)
    assert fault.replayed_grants == [payload["call"]["operation_id"]]


@pytest.mark.parametrize("change", ["same_id", "old_tuning", "other_receipt"])
def test_bad_observation_does_not_pass_acceptance(change):
    fault, payload, response = observation()
    if change == "same_id":
        payload["call"]["operation_id"] = response["operation"]["operation_id"]
    elif change == "old_tuning":
        payload["call"]["canonical_request"] = json.dumps({"max_tokens": 4096})
    else:
        response = deepcopy(response)
        response["operation"]["receipt"]["completion"] += 1
    with pytest.raises(AssertionError):
        observe_replay(fault, payload, response)
    assert not fault.replayed_grants


@pytest.mark.parametrize("boundary", [None, {"opcode": "checkpoint"}])
def test_normal_checkpoint_or_new_grant_is_not_a_completed_alias(boundary):
    fault, payload, response = observation()
    fault.boundary = boundary
    response["operation"].pop("operation_id")
    observe_replay(fault, payload, response)
    assert not fault.replayed_grants
