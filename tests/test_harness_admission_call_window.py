"""Вопрос даёт новую информацию, а не новый денежный бюджет или попытку транспорта."""

import json
from types import SimpleNamespace
from uuid import uuid4

from service.services.chat.persistence.harness.admission.calls import stored_call
from service.services.chat.persistence.harness.grants import precontract_limit_reached
from service.services.chat.persistence.harness.model_requests import matching_request
from service.shared.harness_protocol import PaidCall
from service.shared.task_contract import digest_payload


def request(*, contract=True, window=None):
    body = {"messages": [{"role": "user", "content": "Синтетическая цель"}]}
    if contract:
        body["tools"] = [{"type": "function", "function": {"name": "submit_task_contract"}}]
    raw = {"kind": "meta_usage", "canonical_request": json.dumps(body)}
    if window:
        raw["_admission_job_v1"] = window
    return raw


def call():
    return SimpleNamespace(**request(), billing_tool=None)


def test_answered_child_does_not_inherit_exhausted_preanswer_extraction_window():
    root, child = str(uuid4()), str(uuid4())
    row = {"checkpoint": None, "task_id": root, "active_job_id": child}
    grants = [{"request": request(window=root)} for _ in range(2)]
    assert not precontract_limit_reached(row, call(), grants)


def test_planning_meta_calls_are_not_contract_protocol_repairs():
    root = str(uuid4())
    row = {"checkpoint": None, "task_id": root, "active_job_id": root}
    grants = [{"request": request(contract=False)} for _ in range(2)]
    assert not precontract_limit_reached(row, call(), grants)


def test_transport_retry_cannot_reset_two_contract_calls_for_same_child_job():
    root, child = str(uuid4()), str(uuid4())
    row = {"checkpoint": None, "task_id": root, "active_job_id": child}
    grants = [{"request": request(window=child)} for _ in range(2)]
    assert precontract_limit_reached(row, call(), grants)


def test_legacy_unknown_meta_calls_remain_conservative_in_root_window():
    root = str(uuid4())
    row = {"checkpoint": None, "task_id": root, "active_job_id": root}
    grants = [{"request": {"kind": "meta_usage"}} for _ in range(2)]
    assert precontract_limit_reached(row, call(), grants)


def test_server_window_is_not_part_of_wire_intent_or_authorization():
    root = str(uuid4())
    row = {"checkpoint": None, "task_id": root, "active_job_id": root}
    contract = PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test",
        prompt=1000,
        completion=100,
        request_digest="a" * 64,
        **request(),
    )
    stored = stored_call(row, contract)
    assert stored["_admission_job_v1"] == root
    wire = contract.model_dump(mode="json")
    assert matching_request({"request": stored, "request_digest": digest_payload(wire)}, contract)
    assert matching_request({"request": stored, "request_digest": digest_payload(stored)}, contract)
    assert not matching_request({"request": stored, "request_digest": "f" * 64}, contract)
