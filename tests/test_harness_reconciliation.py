"""Offline lost-ACK corpus. The journal and provider transports are fakes.

This verifies client decisions, not PostgreSQL crash recovery or workspace writes.
"""

import hashlib
import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.domain.client.calls.harness_transport import paid_chat
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.harness.tools import execute_harness_tool
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.runners.tool_runtime.execution import ValidatedToolCall
from service.infrastructure.harness.client import HarnessClient
from service.shared.harness_protocol import (
    Admission,
    Continuation,
    EffectIntent,
    HarnessFailure,
    PaidCall,
    Snapshot,
)
from service.shared.task_contract import TaskContract, TaskState, digest_payload
from tests.test_harness_runtime import response


def current():
    contract = TaskContract(
        task_id=str(uuid4()),
        project_id="project",
        generation="generation",
        goal="PRIVATE_GOAL",
        kind="change",
        actions=["read", "write", "exec"],
        credit_limit=10000,
        criteria=[{"criterion_id": "source", "kind": "file", "target": "a.py"}],
    )
    return Snapshot(
        admission=Admission(
            task_id=contract.task_id,
            project_id=contract.project_id,
            generation=contract.generation,
            goal=contract.goal,
            surface="ide",
            source_revision="r1",
            actions=contract.actions,
            credit_limit=contract.credit_limit,
            reservation_id=str(uuid4()),
        ),
        state=TaskState(contract=contract, source_revision="r1", rounds=3),
        revision=4,
    )


class Journal:
    def __init__(self, lost):
        self.current = current()
        self.operations = {}
        self.counts = Counter()
        self.lost = lost
        self.checkpoint_change = None

    def client(self):
        client = HarnessClient(
            {"task_id": self.current.admission.task_id, "capability": "PRIVATE_CAP"},
            transport=httpx.MockTransport(self),
        )
        client.current = self.current
        return client

    def __call__(self, request):
        payload = json.loads(request.content)
        opcode = payload["opcode"]
        self.counts[opcode] += 1
        if opcode in {"grant", "prepare_effect"}:
            paid = opcode == "grant"
            value = payload["call" if paid else "effect"]
            value = (
                (PaidCall if paid else EffectIntent).model_validate(value).model_dump(mode="json")
            )
            kind = "paid" if paid else "effect"
            record = self.operations.setdefault(
                (kind, value["operation_id"]),
                {
                    "operation_kind": kind,
                    "operation_id": value["operation_id"],
                    "request_digest": digest_payload(value),
                    "status": "allocated" if paid else "prepared",
                    "receipt": None,
                },
            )
            result = {"operation": {"status": record["status"], "receipt": record["receipt"]}}
        elif opcode in {"dispatch", "dispatch_effect"}:
            record = self.operations[
                ("paid" if opcode == "dispatch" else "effect", payload["operation_id"])
            ]
            allowed = record["status"] in {"allocated", "prepared"}
            record["status"] = "dispatched"
            result = {"operation": {"status": record["status"], "dispatch_allowed": allowed}}
        elif opcode in {"call_receipt", "effect_receipt"}:
            paid = opcode == "call_receipt"
            receipt = payload["receipt" if paid else "effect_result"]
            record = self.operations[("paid" if paid else "effect", receipt["operation_id"])]
            record.update(status=receipt["status"], receipt=receipt)
            result = {"operation": {"status": record["status"]}}
        elif opcode == "operation_status":
            result = {
                "operation_status": self.operations[
                    (payload["operation_kind"], payload["operation_id"])
                ]
            }
        elif opcode == "checkpoint":
            state = TaskState.model_validate(payload["state"])
            raw = state.model_dump(mode="json")
            if state != self.current.state:
                raw["revision"] = self.current.state.revision + 1
            if self.checkpoint_change:
                raw.update(self.checkpoint_change)
            self.current = Snapshot(
                admission=self.current.admission,
                revision=self.current.revision + 1,
                state=TaskState.model_validate(raw),
                continuation=Continuation.model_validate(payload["continuation"]),
            )
            result = {"snapshot": self.current.model_dump(mode="json")}
        elif opcode == "state":
            result = {"snapshot": self.current.model_dump(mode="json")}
        else:
            raise AssertionError("unexpected exchange")
        if opcode == self.lost and self.counts[opcode] == 1:
            raise httpx.ReadTimeout("PRIVATE_ACK_DIAGNOSTIC")
        return httpx.Response(200, json=result)


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["grant", "call_receipt"])
async def test_committed_paid_record_restores_ack_without_another_provider_call(lost):
    journal = Journal(lost)
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock(return_value=response())
        result, _ = await paid_chat(
            send, provider="openai", model="test", payload={"max_tokens": 100}
        )
        assert result.choices[0].message.content == "done"
        assert send.await_count == journal.counts["dispatch"] == 1
        assert journal.counts[lost] == journal.counts["operation_status"] == 1
        assert client.failure == "" and len(execution.usage.receipts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["prepare_effect", "effect_receipt"])
async def test_committed_effect_record_does_not_repeat_adapter(lost):
    journal = Journal(lost)
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        execution.bind_task_state(journal.current.state)

        async def write():
            execution.workspace.ide_writes["a.py"] = hashlib.sha256(b"contents").hexdigest()
            return ToolCallOutcome('{"written":true}', "succeeded", 0)

        invoke = AsyncMock(side_effect=write)
        call = ValidatedToolCall(
            0, "write1", "ide_write_file", {"path": "a.py"}, "{}", '{"path":"a.py"}', "key"
        )
        outcome = await execute_harness_tool(call, invoke)
        assert outcome.succeeded and invoke.await_count == 1
        assert len(execution.task_state.evidence) == 1 and client.failure == ""
        assert journal.counts["dispatch_effect"] == journal.counts[lost] == 1
        effect = next(
            item for item in journal.operations.values() if item["operation_kind"] == "effect"
        )
        assert effect["receipt"]["charged"] is True


@pytest.mark.asyncio
async def test_rejected_adapter_records_explicit_nonbillable_proof():
    journal = Journal(None)
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        execution.bind_task_state(journal.current.state)
        call = ValidatedToolCall(
            0, "write1", "ide_write_file", {"path": "a.py"}, "{}", '{"path":"a.py"}', "key"
        )
        invoke = AsyncMock(return_value=ToolCallOutcome("conflict", "failed", 0))
        result = await execute_harness_tool(call, invoke)
        assert not result.succeeded and not execution.task_state.evidence
    effect = next(
        item for item in journal.operations.values() if item["operation_kind"] == "effect"
    )
    paid = next(item for item in journal.operations.values() if item["operation_kind"] == "paid")
    assert effect["receipt"]["charged"] is False and paid["status"] == "waived"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [None, {"rounds": 10}, {"source_revision": "user-edit"}])
async def test_checkpoint_ack_requires_exact_state_and_preserves_counters(changed):
    journal = Journal("checkpoint")
    journal.checkpoint_change = changed
    client = journal.client()
    values = dict(
        opcode="checkpoint",
        expected_revision=client.current.revision,
        state=client.current.state.claim_round(),
        continuation=Continuation(next_step=1),
    )
    if changed:
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await client.exchange(**values)
        assert client.failure == "checkpoint_unavailable"
    else:
        await client.exchange(**values)
        assert client.current.state.rounds == 4 and client.current.continuation.next_step == 1
        assert client.failure == ""
    assert journal.counts["checkpoint"] == journal.counts["state"] == 1


@pytest.mark.asyncio
async def test_lost_dispatch_ack_is_not_authorized_by_journal_inspection():
    journal = Journal("dispatch")
    client = journal.client()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock()
        with pytest.raises(HarnessFailure):
            await paid_chat(send, provider="openai", model="test", payload={"max_tokens": 100})
        send.assert_not_awaited()
        assert journal.counts["dispatch"] == 1 and journal.counts["operation_status"] == 0
        assert client.failure == "checkpoint_unavailable"


@pytest.mark.asyncio
async def test_checkpoint_budget_does_not_drop_ack_latency(monkeypatch):
    from service.infrastructure.harness import client as harness_client

    clock = {"now": 0}
    monkeypatch.setattr(harness_client, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    journal = Journal(None)
    client = journal.client()
    original = journal.__class__.__call__

    def delayed(self, request):
        result = original(self, request)
        if json.loads(request.content)["opcode"] == "checkpoint":
            clock["now"] += 10
        return result

    monkeypatch.setattr(Journal, "__call__", delayed)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        execution.bind_task_state(journal.current.state)
        clock["now"] = 10
        await client.checkpoint(execution, [], phase="model")
        assert execution.task_state.budget.active_ms == 10000 and clock["now"] == 20
        clock["now"] = 30
        await client.checkpoint(execution, [], phase="model")
        assert execution.task_state.budget.active_ms == 30000


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,digest",
    [
        ("dispatched", None),
        ("unknown", None),
        ("allocated", "b" * 64),
    ],
)
async def test_unknown_or_mismatched_intent_never_authorizes_dispatch(status, digest):
    from service.infrastructure.harness.reconciliation import reconcile_exchange
    from service.shared.harness_protocol import Exchange

    call = PaidCall(
        operation_id=str(uuid4()),
        provider="openai",
        model="test",
        prompt=100,
        completion=10,
        request_digest="a" * 64,
    )
    query = AsyncMock(
        return_value={
            "operation_status": {
                "operation_id": call.operation_id,
                "operation_kind": "paid",
                "status": status,
                "request_digest": digest or digest_payload(call.model_dump(mode="json")),
            }
        }
    )
    assert await reconcile_exchange(Exchange(opcode="grant", call=call), None, query) is None
    query.assert_awaited_once_with(
        opcode="operation_status", operation_id=call.operation_id, operation_kind="paid"
    )


@pytest.mark.asyncio
async def test_uncertain_usage_receipt_cannot_be_promoted_by_ack_reconciliation():
    from service.shared.harness_protocol import CallReceipt

    journal = Journal("call_receipt")
    client = journal.client()
    operation_id = str(uuid4())
    journal.operations[("paid", operation_id)] = {
        "operation_id": operation_id,
        "operation_kind": "paid",
        "request_digest": "a" * 64,
        "status": "dispatched",
        "receipt": None,
    }
    receipt = CallReceipt(operation_id=operation_id, status="unknown", prompt=10, estimated=True)
    result = await client.exchange(opcode="call_receipt", receipt=receipt)
    assert result["operation"]["status"] == "unknown"
    assert journal.operations[("paid", operation_id)]["status"] == "unknown"
    assert journal.counts["call_receipt"] == journal.counts["operation_status"] == 1
