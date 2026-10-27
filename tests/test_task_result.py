"""Harness stop evidence survives persistence without arbitrary private fields."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from service.services.chat.domain.task_result import TaskResult
from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.shared.task_contract import TaskResultV2


def payload():
    return {
        "schema_version": 1,
        "status": "partial",
        "blocker": "no_progress",
        "rounds": 3,
        "repair_cycles": 0,
        "verified": False,
    }


def test_harness_stop_survives_message_persistence():
    assert persistable_meta({"task_result": payload()}, None)["task_result"] == payload()


@pytest.mark.parametrize(
    "patch",
    [
        {"verified": True},
        {"status": "completed"},
        {"repair_cycles": 3},
        {"rounds": True},
        {"blocker": "PRIVATE_EXCEPTION"},
        {"transcript": "PRIVATE"},
    ],
)
def test_unverified_stop_cannot_invent_success_or_leak_private_fields(patch):
    raw = {**payload(), **patch}
    with pytest.raises(ValidationError):
        TaskResult.model_validate(raw)
    assert "task_result" not in persistable_meta({"task_result": raw}, None)


def test_public_projection_matches_protocol_manifest():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "service/infrastructure/agents_client/contracts/protocol_manifest.json").read_text()
    )["task_result"]
    assert set(TaskResult.model_fields["status"].annotation.__args__) == set(manifest["statuses"])
    assert set(TaskResult.model_fields["blocker"].annotation.__args__) == set(manifest["blockers"])
    assert manifest["supported_versions"] == [1, 2]
    assert set(TaskResultV2.model_fields["status"].annotation.__args__) == set(
        manifest["v2"]["statuses"]
    )


def test_v2_projection_survives_persistence_without_changing_v1():
    value = {
        "schema_version": 2,
        "status": "partial",
        "verified": False,
        "blocker": "verification_missing",
        "confirmed": [],
        "unchecked": ["test"],
        "references": [],
        "rounds": 8,
        "repair_cycles": 1,
    }
    assert persistable_meta({"task_result": value}, None)["task_result"] == value
    assert persistable_meta({"task_result": payload()}, None)["task_result"] == payload()
    assert "task_result" not in persistable_meta(
        {"task_result": {**value, "provider_state": "PRIVATE"}}, None
    )
