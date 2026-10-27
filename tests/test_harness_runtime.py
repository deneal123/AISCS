"""Offline acknowledged-client regressions; provider and backend transport are fakes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from openai.types.chat import ChatCompletion

from service.domain.client.calls.harness_transport import paid_chat
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.infrastructure.harness.client import HarnessClient
from service.shared.harness_protocol import Admission, HarnessFailure, Snapshot


def snapshot():
    return Snapshot(
        admission=Admission(
            task_id=str(uuid4()),
            project_id="project",
            generation="generation",
            surface="ide",
            goal="PRIVATE_GOAL",
            source_revision="r1",
            actions=["read", "write", "exec"],
            credit_limit=10000,
            reservation_id=str(uuid4()),
        )
    )


def response():
    return ChatCompletion.model_validate(
        {
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "done",
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
    )


@pytest.mark.asyncio
async def test_cached_paid_response_is_not_dispatched_or_billed_twice():
    current = snapshot()
    receipts = {}
    dispatches = []

    def backend(request):
        payload = json.loads(request.content)
        if payload["opcode"] == "grant":
            operation_id = payload["call"]["operation_id"]
            value = (
                {"status": "succeeded", "receipt": receipts[operation_id]}
                if operation_id in receipts
                else {"status": "allocated"}
            )
        elif payload["opcode"] == "dispatch":
            dispatches.append(payload["operation_id"])
            value = {"dispatch_allowed": True}
        elif payload["opcode"] == "call_receipt":
            receipts[payload["receipt"]["operation_id"]] = payload["receipt"]
            value = {"status": "succeeded"}
        else:
            raise AssertionError("unexpected exchange")
        return httpx.Response(200, json={"operation": value})

    client = HarnessClient(
        {"task_id": current.admission.task_id, "capability": "PRIVATE_CAP"},
        transport=httpx.MockTransport(backend),
    )
    client.current = current
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock(return_value=response())
        payload = {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 100}
        first, key = await paid_chat(send, provider="openai", model="test", payload=payload)
        second, repeat = await paid_chat(send, provider="openai", model="test", payload=payload)
        assert first.choices[0].message.content == second.choices[0].message.content
        assert key == repeat and send.await_count == 1 and len(dispatches) == 1
        assert len(execution.usage.receipts) == 1


@pytest.mark.asyncio
async def test_lost_dispatch_ack_never_calls_provider():
    current = snapshot()

    def backend(request):
        payload = json.loads(request.content)
        if payload["opcode"] == "grant":
            return httpx.Response(200, json={"operation": {"status": "allocated"}})
        raise httpx.ReadTimeout("PRIVATE_TRANSPORT")

    client = HarnessClient(
        {"task_id": current.admission.task_id, "capability": "PRIVATE_CAP"},
        transport=httpx.MockTransport(backend),
    )
    client.current = current
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        send = AsyncMock()
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await paid_chat(send, provider="openai", model="test", payload={"max_tokens": 10})
        send.assert_not_awaited()
        assert client.failure == "checkpoint_unavailable"


def test_harness_capability_never_enters_tool_or_prompt_context():
    from service.domain.execution.context import prompt_safe_context_payload, tool_context_payload

    resources = PrivateRunResources(workspace_ref={"harness_ref": {"capability": "PRIVATE_CAP"}})
    with use_run_execution(resources):
        context = SimpleNamespace()
        assert "PRIVATE_CAP" not in str(prompt_safe_context_payload(context))
        assert "PRIVATE_CAP" not in str(tool_context_payload(context, "ide_read_file"))


@pytest.mark.asyncio
async def test_resume_restores_write_readback_and_rejects_changed_bytes(monkeypatch):
    import hashlib

    from service.application.harness import admission as harness_admission
    from service.domain.runners.ide import verification as ide_verification
    from service.shared.task_contract import TaskContract, TaskEvidence, TaskState

    current = snapshot()
    expected = hashlib.sha256(b"expected").hexdigest()
    state = TaskState(
        contract=TaskContract(
            task_id=current.admission.task_id,
            project_id="project",
            generation="generation",
            kind="change",
            goal="PRIVATE_GOAL",
            actions=["read", "write", "exec"],
            criteria=[{"criterion_id": "file", "kind": "file", "target": "a.py"}],
            credit_limit=10000,
        ),
        source_revision="r1",
        evidence=[
            TaskEvidence(
                criterion_id="file",
                operation_id=str(uuid4()),
                kind="file",
                target="a.py",
                source_revision="r1",
                digest=expected,
                outcome="passed",
            )
        ],
    )
    current = Snapshot(admission=current.admission, state=state)
    monkeypatch.setattr(
        harness_admission,
        "HarnessClient",
        lambda _: SimpleNamespace(load=AsyncMock(return_value=current)),
    )
    changed = "changed by user"
    remote = AsyncMock(
        return_value={
            "path": "a.py",
            "kind": "text",
            "content": changed,
            "size": len(changed),
            "digest": hashlib.sha256(changed.encode()).hexdigest(),
            "truncated": False,
        }
    )
    monkeypatch.setattr(ide_verification, "call", remote)
    reference = {"harness_ref": {}, "ide_context": {}}
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        await harness_admission.install_harness(execution)
        assert execution.workspace.ide_writes == {"a.py": expected}
        await ide_verification.finalize_ide_evidence(execution)
        assert execution.task.stop_reason == "verification_failed"
        remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_uses_frozen_model_without_routing_again(monkeypatch):
    from service.application.admission.document import resolve_execution_model
    from service.application.use_cases.agent_execution_use_cases import RouteModelUseCase
    from service.shared.harness_protocol import Continuation, ProviderBinding

    current = snapshot()
    current = Snapshot(
        admission=current.admission,
        continuation=Continuation(provider=ProviderBinding(provider="openai", model="frozen")),
    )
    route = AsyncMock(side_effect=AssertionError("must not route a recovered conversation"))
    monkeypatch.setattr(RouteModelUseCase, "execute", route)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = SimpleNamespace(current=current)
        result = await resolve_execution_model(
            text="PRIVATE_GOAL",
            selected_model=None,
            input_type="text",
            route_override="general",
            resolved_category="general",
            execution=execution,
            on_event=None,
        )
        assert result == ("frozen", {})
        route.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("untyped", ['{"status":"invalid"}', "written", None])
async def test_untyped_effect_cannot_be_confirmed_or_charged(untyped):
    from service.domain.runners.harness.tools import execute_harness_tool
    from service.domain.runners.tool_runtime.execution import ValidatedToolCall
    from tests.test_task_contract import state

    task = state()
    exchanges = []

    async def exchange(**payload):
        exchanges.append(payload["opcode"])
        if payload["opcode"] == "prepare_effect":
            return {"operation": {"status": "prepared"}}
        if payload["opcode"] == "grant":
            return {"operation": {"status": "allocated"}}
        return {"operation": {"status": "dispatched", "dispatch_allowed": True}}

    call = ValidatedToolCall(
        position=0,
        call_id="write1",
        name="ide_write_file",
        arguments={"path": "a.py"},
        invoke_arguments='{"path":"a.py"}',
        canonical_arguments='{"path":"a.py"}',
        cache_key="write1",
    )
    client = SimpleNamespace(
        task_id=task.contract.task_id,
        failure="",
        exchange=exchange,
        current=SimpleNamespace(
            continuation=SimpleNamespace(next_step=0),
            admission=SimpleNamespace(surface="ide", actions=task.contract.actions),
        ),
    )
    with use_run_execution(PrivateRunResources()) as execution:
        execution.bind_task_state(task)
        execution.harness = client
        with pytest.raises(HarnessFailure, match="unsupported_adapter"):
            await execute_harness_tool(call, AsyncMock(return_value=untyped))
        assert client.failure == "operation_unknown"
        assert execution.task_state.evidence == ()
        assert exchanges == ["prepare_effect", "grant", "dispatch", "dispatch_effect"]
