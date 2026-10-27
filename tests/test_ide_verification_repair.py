"""Проваленная проверка ведёт к исправлению, а не к неподтверждённому успеху."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    compile_toolset,
)
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat.stream_loop import run_streamed_tool_loop
from service.domain.runners.harness.continuation import advance_model_continuation
from service.domain.runners.ide.repair import (
    INCOMPLETE_MESSAGE,
    prepare_verification_repair,
    withhold_unverified_text,
)
from service.domain.tools.ide.finish import summary_for_result
from service.events import EventType
from service.shared.harness_protocol import HarnessFailure
from service.shared.task_contract import (
    TaskBudget,
    TaskContract,
    TaskCriterion,
    TaskEvidence,
    TaskState,
)
from tests.test_harness_model_continuation import Journal
from tests.test_s25_grounding_latch import _Disclosure, _state, _stream_script, _tool

TOOLS = ["ide_read_file", "ide_edit_file", "ide_run_command", "ide_finish_task"]


def evidence(kind="command", outcome="failed", revision="r1"):
    return TaskEvidence(
        criterion_id="check" if kind == "command" else "script",
        operation_id=str(uuid4()),
        kind=kind,
        target="hello.py",
        source_revision=revision,
        digest="a" * 64,
        outcome=outcome,
        exit_code=0 if kind == "command" else None,
    )


def bind(execution, **updates):
    execution.bind_task_state(
        TaskState(
            contract=TaskContract(
                task_id=str(uuid4()),
                project_id="synthetic-project",
                generation="g1",
                goal="Создать hello.py и проверить точный вывод",
                kind="change",
                actions=("read", "write", "exec"),
                criteria=(
                    TaskCriterion(criterion_id="script", kind="file", target="hello.py"),
                    TaskCriterion(criterion_id="check", kind="command", target="hello.py"),
                ),
                credit_limit=100,
            ),
            source_revision="r1",
            evidence=(evidence("file", "passed"), evidence()),
            **updates,
        )
    )
    execution.harness = Journal()
    state = _state(execution, _Disclosure([_tool(name) for name in TOOLS]))
    state.tool_index = dict.fromkeys(TOOLS, object())
    state.max_tool_rounds = 16
    state.tool_choice = None
    return state


def test_failed_receipt_adds_one_private_nudge_and_only_policy_allowed_tools():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        allowed = [_tool("ide_read_file"), _tool("ide_finish_task")]
        state.disclosure_controller.eligible_toolset = SimpleNamespace(tools=allowed)
        assert prepare_verification_repair(state)
        assert state.tool_choice == {"type": "function", "function": {"name": "ide_read_file"}}
        assert [item["function"]["name"] for item in state.openai_tools] == ["ide_read_file"]
        assert state.convo[-1]["role"] == "user"
        assert "check" in state.convo[-1]["content"]
        assert "Не ослабляй проверку" in state.convo[-1]["content"]
        assert not prepare_verification_repair(state)
        assert execution.task_state.repairs == execution.task_state.protocol_repairs == 0


@pytest.mark.parametrize(
    "guard",
    ["cancel", "backend", "unconfirmed", "repairs", "rounds", "held", "stop", "missing", "unknown"],
)
def test_repair_does_not_bypass_stop_limits_or_uncertainty(guard):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        if guard == "cancel":
            execution.cancel()
        elif guard == "backend":
            execution.harness.failure = "operation_unknown"
        elif guard == "unconfirmed":
            execution.workspace.ide_unconfirmed = True
        elif guard == "repairs":
            execution.task_state = execution.task_state.advance(repairs=2)
        elif guard == "rounds":
            execution.task_state = execution.task_state.advance(rounds=16)
        elif guard == "held":
            execution.task_state = execution.task_state.advance(budget=TaskBudget(held_credits=1))
        elif guard == "stop":
            execution.task.stop_reason = "no_progress"
        elif guard == "unknown":
            execution.task_state = execution.task_state.advance(
                evidence=(*execution.task_state.evidence, evidence("file", "unknown"))
            )
        else:
            state.tool_index = {}
        before = list(state.convo)
        assert not prepare_verification_repair(state)
        assert state.convo == before


def test_resume_restores_pending_repair_choice_without_another_message_or_round():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        assert prepare_verification_repair(state)
        saved = list(state.convo)
        state.tool_choice = None
        state.openai_tools = [_tool(name) for name in TOOLS]
        assert not prepare_verification_repair(state)
        assert state.convo == saved
        assert state.tool_choice == {"type": "function", "function": {"name": "ide_read_file"}}
        assert "ide_finish_task" not in [tool["function"]["name"] for tool in state.openai_tools]
        assert execution.task_state.repairs == execution.task_state.rounds == 0


def test_report_stays_out_of_repair_tools_until_a_new_check_confirms_the_result():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        state.disclosure_controller.eligible_toolset = SimpleNamespace(tools=state.openai_tools)
        assert prepare_verification_repair(state)
        state.convo.append({"role": "assistant", "content": "Исходник прочитан; исправляю ошибку."})
        state.openai_tools = [_tool(name) for name in TOOLS]
        assert not prepare_verification_repair(state)
        assert state.tool_choice is None
        assert "ide_finish_task" not in [tool["function"]["name"] for tool in state.openai_tools]
        assert len([message for message in state.convo if message["role"] == "user"]) == 2


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_repair_choice_compiles_without_provider_specific_weakening(provider):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        assert prepare_verification_repair(state)
        compiled = compile_toolset(
            state.openai_tools,
            provider=provider,
            capabilities=GIGACHAT_TOOL_CAPABILITIES
            if provider == "gigachat"
            else OPENAI_TOOL_CAPABILITIES,
            tool_choice=state.tool_choice,
        )
        assert compiled.choice == (
            {"name": "ide_read_file"}
            if provider == "gigachat"
            else {"type": "function", "function": {"name": "ide_read_file"}}
        )


@pytest.mark.asyncio
async def test_repair_checkpoint_ack_is_required_before_next_paid_dispatch():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        assert prepare_verification_repair(state)
        execution.harness.fail_advance = True
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await advance_model_continuation(state, agent_name="general")
        assert not execution.harness.dispatches


@pytest.mark.asyncio
async def test_failed_check_is_repaired_before_verified_report_is_published():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        state.disclosure_controller.eligible_toolset = SimpleNamespace(tools=state.openai_tools)
        assert prepare_verification_repair(state)
        await advance_model_continuation(state, agent_name="general")
        executed, observed = [], []

        async def backend_result(**kwargs):
            return {"result": execution.completion_verifier.evaluate(execution.task_state)}

        execution.harness.exchange = AsyncMock(side_effect=backend_result)

        async def execute(convo, calls, *_args, **_kwargs):
            convo.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                        for call in calls
                    ],
                }
            )
            for call in calls:
                name = call["name"]
                executed.append(name)
                if name == "ide_edit_file":
                    execution.task_state = execution.task_state.advance(source_revision="r2")
                if name == "ide_run_command":
                    execution.task_state = execution.task_state.advance(
                        repairs=1,
                        evidence=(
                            *execution.task_state.evidence,
                            evidence("file", "passed", "r2"),
                            evidence("command", "passed", "r2"),
                        ),
                    )
                if name == "ide_finish_task":
                    execution.workspace.ide_summary = "Файл исправлен; точный вывод проверен."
                convo.append({"role": "tool", "tool_call_id": call["id"], "content": "{}"})
            await execution.harness.checkpoint(execution, convo, phase="model", advance=True)
            if False:
                yield

        choices = []
        script = _stream_script(
            [
                {
                    "text": "ЛОЖНЫЙ УСПЕХ" if name != "ide_finish_task" else "",
                    "tool_calls": [{"id": str(index), "name": name, "arguments": "{}"}],
                    "finish_reason": "tool_calls",
                }
                for index, name in enumerate(
                    ["ide_read_file", "ide_edit_file", "ide_run_command", "ide_finish_task"]
                )
            ],
            choices,
        )

        async def stream(**kwargs):
            execution.harness.dispatch(kwargs["messages"])
            observed.append(kwargs)
            async for value in script(**kwargs):
                yield value

        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=execute,
                estimate_prompt_tokens=lambda *_: 1,
                stream=stream,
            )
        ]
        text = "".join(event.data or "" for event in events if event.type == EventType.STREAM_CHUNK)
        assert "ЛОЖНЫЙ УСПЕХ" not in text
        assert "точный вывод проверен" in text
        assert executed == ["ide_read_file", "ide_edit_file", "ide_run_command", "ide_finish_task"]
        assert choices[0] == {"type": "function", "function": {"name": "ide_read_file"}}
        assert "ide_finish_task" not in [tool["function"]["name"] for tool in observed[0]["tools"]]
        assert execution.task_state.repairs == 1 and execution.task_state.protocol_repairs == 0


@pytest.mark.asyncio
async def test_unverified_plain_text_and_summary_cannot_claim_success():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        execution.workspace.ide_summary = "Файл создан и проверен."
        state.tool_index = {}
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=None,
                estimate_prompt_tokens=lambda *_: 1,
                stream=_stream_script([{"text": "Задача выполнена!"}], []),
            )
        ]
        assert [event.data for event in events if event.type == EventType.STREAM_CHUNK] == [
            INCOMPLETE_MESSAGE
        ]
        assert "не завершено" in summary_for_result(
            execution, task_result=execution.completion_verifier.evaluate(execution.task_state)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_completed", [False, True])
async def test_local_proof_alone_cannot_publish_success_before_backend_result(backend_completed):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        execution.task_state = execution.task_state.advance(
            evidence=(*execution.task_state.evidence, evidence("command", "passed"))
        )
        result = execution.completion_verifier.evaluate(execution.task_state)
        if not backend_completed:
            result.update(status="partial", verified=False, blocker="binding_changed")
        execution.harness.exchange = AsyncMock(return_value={"result": result})
        state.tool_index = {}
        events = [
            event
            async for event in run_streamed_tool_loop(
                state,
                agent_name="general",
                execute_tool_round=None,
                estimate_prompt_tokens=lambda *_: 1,
                stream=_stream_script([{"text": "ПРОИЗВОЛЬНЫЙ ТЕКСТ МОДЕЛИ"}], []),
            )
        ]
        text = "".join(event.data or "" for event in events if event.type == EventType.STREAM_CHUNK)
        assert "ПРОИЗВОЛЬНЫЙ ТЕКСТ МОДЕЛИ" not in text
        assert ("Задание выполнено" in text) is backend_completed
        assert (text == INCOMPLETE_MESSAGE) is not backend_completed
        execution.harness.exchange.assert_awaited_once_with(opcode="result")
        assert (
            "Задание выполнено" in summary_for_result(execution, task_result=result)
        ) is backend_completed


@pytest.mark.parametrize("surface", [None, "document_context"])
def test_ordinary_chat_and_pdf_keep_their_existing_text_policy(surface):
    reference = {surface: {}} if surface else None
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        bind(execution)
        assert not withhold_unverified_text(execution)


def test_repaired_current_revision_stops_coaching_but_stale_proof_does_not_complete():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        execution.task_state = execution.task_state.advance(
            evidence=(*execution.task_state.evidence, evidence("command", "passed"))
        )
        assert withhold_unverified_text(execution)
        assert not prepare_verification_repair(state)
        assert execution.completion_verifier.evaluate(execution.task_state)["status"] == "completed"
        execution.task_state = execution.task_state.advance(source_revision="r2")
        assert execution.completion_verifier.evaluate(execution.task_state)["status"] != "completed"


def test_old_continuation_without_feedback_cannot_skip_a_previously_paid_model_response():
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        before = list(state.convo)
        assert not prepare_verification_repair(state, restore_only=True)
        assert state.convo == before and state.tool_choice is None
        assert not execution.harness.checkpoints


@pytest.mark.asyncio
async def test_failed_tool_receipt_and_repair_note_share_one_atomic_model_checkpoint(monkeypatch):
    from service.domain.runners.chat import tool_loop

    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        state = bind(execution)
        owner = tool_loop.ToolRoundMixin()
        owner.name = "general"
        monkeypatch.setattr(
            tool_loop,
            "execute_tool_calls",
            AsyncMock(
                return_value=[tool_loop.ToolCallOutcome("Проверка не пройдена", "failed", 0)]
            ),
        )
        calls = [{"id": "command-1", "name": "ide_run_command", "arguments": "{}"}]
        _ = [
            event
            async for event in owner._execute_tool_round(
                state.convo,
                calls,
                state.tool_index,
                {},
                "",
                set(),
                round_number=1,
            )
        ]
        journal = execution.harness
        assert len(journal.checkpoints) == 2
        assert [advance for advance, *_ in journal.checkpoints] == [False, True]
        assert journal.current.continuation.next_step == 1
        assert journal.checkpoints[-1][2][-1]["content"].startswith("[harness:verification-repair:")
        assert not prepare_verification_repair(state, restore_only=True)
        assert state.tool_choice == {"type": "function", "function": {"name": "ide_read_file"}}
