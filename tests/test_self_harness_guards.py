"""Real tool adapter and dispatcher regressions, with no model/network access."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.execution.progress import TaskProgress
from service.domain.runners.chat.preparation import _tool_rounds_for
from service.domain.runners.support import invoke_tool_outcome
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.subagents.general import GeneralAgent
from service.domain.tools import document_proposal_tool
from service.domain.tools.ide import tools as ide_tools


@pytest.mark.asyncio
async def test_invalid_pdf_patch_is_not_successful_grounding_or_billable():
    with use_run_execution(PrivateRunResources()) as execution:
        outcome = await invoke_tool_outcome(
            document_proposal_tool.tool, SimpleNamespace(context={}), "{}"
        )
        assert outcome.status == "invalid"
        assert not outcome.succeeded and not outcome.charged
        assert json.loads(outcome.text)["status"] == "invalid"
        assert json.loads(outcome.text)["error_code"] == "invalid_patch"
        assert not execution.policy.values.get("document_proposal")


def test_file_budget_uses_capability_metadata_not_name_prefix():
    def tool(name):
        return {"function": {"name": name}}

    assert _tool_rounds_for(4, [tool("ide_read_file")]) == 8
    assert _tool_rounds_for(4, [tool("ws_unknown_not_registered")]) == 4
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})):
        assert _tool_rounds_for(4, [tool("ide_read_file")]) == 16
        assert _tool_rounds_for(100, [tool("ide_read_file")]) == 16


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ide_context", "document_context"])
async def test_native_openai_product_run_never_enters_sdk_loop(monkeypatch, surface):
    from service.domain.client.providers.management import compat as provider_compat

    monkeypatch.setattr(provider_compat, "active_provider_name", lambda: "openai")
    agent = GeneralAgent({"model": "test-model"})
    monkeypatch.setattr(agent, "_input_guardrail_block", AsyncMock(return_value=None))
    paths = []

    async def chat(*args):
        paths.append("common")
        if False:
            yield None

    async def sdk(*args):
        raise AssertionError("Product run escaped the common kernel")
        yield

    monkeypatch.setattr(agent, "_run_chat_streamed", chat)
    monkeypatch.setattr(agent, "_run_sdk_streamed", sdk)
    with use_run_execution(PrivateRunResources(workspace_ref={surface: {}})):
        _ = [event async for event in agent.process("Task", None)]
    assert paths == ["common"]


@pytest.mark.asyncio
async def test_unknown_write_ack_prevents_any_further_mutation(monkeypatch):
    remote = AsyncMock(return_value={"written": True})
    monkeypatch.setattr(ide_tools, "call", remote)
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        await ide_tools.ide_write(None, '{"path":"a.py","content":"x","base_digest":""}')
        assert execution.workspace.ide_unconfirmed
        result = await ide_tools.ide_write(None, '{"path":"b.py","content":"y","base_digest":""}')
        assert isinstance(result, ToolCallOutcome) and not result.charged
        assert remote.await_count == 1


def test_three_equivalent_calls_stop_without_exposing_arguments_or_output():
    progress = TaskProgress(active=True)
    outcome = ToolCallOutcome("PRIVATE_OUTPUT", "failed", 0, failure_code="remote")
    for raw in ['{"secret":"PRIVATE", "x":1}', '{"x":1,"secret":"PRIVATE"}'] * 2:
        progress.observe({"name": "tool", "arguments": raw}, outcome, revision="r1")
    assert progress.stop_reason == "no_progress"
    assert "PRIVATE" not in repr(progress)
    result = progress.result(cancelled=False, unconfirmed=False)
    assert result["status"] == "partial" and result["verified"] is False
    assert "PRIVATE" not in json.dumps(result)


def test_revision_change_invalidates_no_progress_observations():
    progress = TaskProgress(active=True)
    outcome = ToolCallOutcome("same output", "succeeded", 0)
    for revision in ("r1", "r1", "r2", "r2"):
        progress.observe({"name": "read", "arguments": "{}"}, outcome, revision=revision)
    assert not progress.stop_reason
    assert progress.result(cancelled=False, unconfirmed=False) is None


def test_reading_file_b_does_not_clear_failed_read_of_file_a():
    progress = TaskProgress(active=True)
    failed = ToolCallOutcome("missing", "failed", 0, failure_code="remote")
    passed = ToolCallOutcome("content", "succeeded", 0)
    a = {"name": "ide_read_file", "arguments": '{"path":"a.py"}'}
    b = {"name": "ide_read_file", "arguments": '{"path":"b.py"}'}
    progress.observe(a, failed, revision="r1")
    progress.observe(b, passed, revision="r1")
    assert progress.result(cancelled=False, unconfirmed=False)["blocker"] == "tool_failed"
    progress.observe(a, passed, revision="r1")
    assert progress.result(cancelled=False, unconfirmed=False) is None


def test_successful_repair_of_same_ide_target_clears_previous_failure():
    progress = TaskProgress(active=True)
    progress.observe(
        {"name": "ide_write_file", "arguments": '{"path":"a.py","content":"bad"}'},
        ToolCallOutcome("conflict", "failed", 0),
        revision="r1",
    )
    progress.observe(
        {"name": "ide_write_file", "arguments": '{"path":"a.py","content":"fixed"}'},
        ToolCallOutcome("confirmed", "succeeded", 0),
        revision="r2",
    )
    assert progress.result(cancelled=False, unconfirmed=False) is None


def test_ide_rounds_are_shared_across_child_loop_entries():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        execution.task.active = True
        for remaining in range(16, 0, -1):
            assert _tool_rounds_for(4, []) == remaining
            assert execution.claim_task_round(limit=16)
        assert _tool_rounds_for(4, []) == 0
        assert not execution.claim_task_round(limit=16)
        assert execution.task.rounds == 16
        assert execution.task.stop_reason == "round_limit"


def test_backend_checkpoint_keeps_rounds_and_criteria_in_run_context():
    from service.shared.task_contract import TaskState
    from tests.test_task_contract import state

    restored = TaskState.model_validate_json(state(rounds=15, repairs=1).model_dump_json())
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        execution.bind_task_state(restored)
        assert execution.task_contract == restored.contract
        assert _tool_rounds_for(4, []) == 1
        assert execution.claim_task_round(limit=16)
        assert execution.task_state.rounds == 16
        assert execution.task_state.repairs == 1
        assert execution.task_state.contract == restored.contract
        assert not execution.claim_task_round(limit=16)


def test_unresolved_tool_failure_cannot_be_reported_as_completed():
    progress = TaskProgress(active=True)
    call = {"name": "patch", "arguments": "{}"}
    progress.observe(call, ToolCallOutcome("bad", "invalid", 0), revision="r1")
    assert progress.result(cancelled=False, unconfirmed=False)["blocker"] == "tool_failed"
    progress.observe(call, ToolCallOutcome("ok", "succeeded", 0), revision="r1")
    assert progress.result(cancelled=False, unconfirmed=False) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ack", ["missing", "different", "valid"])
async def test_ide_completion_reads_back_current_bytes_without_replaying_write(monkeypatch, ack):
    import hashlib

    from service.application.agent_execution_service import _finalize_reply
    from service.application.reply_assembler import ReplyAssembler
    from service.domain.runners.ide import verification as ide_verification

    content = "expected" if ack == "valid" else "changed by user"
    digest = hashlib.sha256(content.encode()).hexdigest()
    response = {
        "path": "a.py",
        "kind": "text",
        "size": len(content.encode()),
        "content": content,
        "digest": digest,
        "truncated": False,
    }
    if ack == "missing":
        response = {"error": "not_found"}
    remote = AsyncMock(return_value=response)
    monkeypatch.setattr(ide_verification, "call", remote)
    reference = {"ide_context": {}}
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        execution.task.active = True
        execution.workspace.ide_writes["a.py"] = hashlib.sha256(b"expected").hexdigest()
        execution.workspace.ide_summary = "Created a.py"
        assembler = ReplyAssembler(execution.usage)
        assembler.reply_parts.append("A detailed reply.")
        result = await _finalize_reply(
            reply_assembler=assembler,
            metadata={},
            timings=SimpleNamespace(as_meta=lambda: {}),
            workspace_ref=reference,
            resolved_model="test",
        )
        remote.assert_awaited_once_with(reference, "ide/file", {"path": "a.py"})
        if ack == "valid":
            assert "task_result" not in result["metadata"]
        else:
            assert result["metadata"]["execution_status"] == "partial"
            assert result["metadata"]["task_result"]["blocker"] == "verification_failed"
            assert result["metadata"]["ide_summary"] != "Created a.py"


@pytest.mark.asyncio
async def test_stop_while_waiting_for_group_lock_does_not_dispatch_next_command():
    from service.domain.runners.tool_runtime import execute_tool_calls

    calls = [{"id": str(i), "name": "command", "arguments": "{}"} for i in range(2)]
    invocations = []
    with use_run_execution(PrivateRunResources()) as execution:

        async def invoke(*args):
            invocations.append("executed")
            await asyncio.sleep(0)  # Let the second call pass admission and wait for the lock.
            execution.cancel()
            return "done"

        outcomes = await execute_tool_calls(
            calls,
            {"command": SimpleNamespace()},
            None,
            concurrency=1,
            invoker=invoke,
            concurrency_group=lambda _: "workspace",
        )
    assert invocations == ["executed"]
    assert outcomes[1].status == "cancelled" and not outcomes[1].charged
