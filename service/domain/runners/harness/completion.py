"""A verified IDE report needs no further paid prose-generation round."""

from service.events import AgentEvent, EventType
from service.shared.task_contract import TaskResultV2


async def verified_ide_report(state, tool_calls, *, agent_name):
    if not tool_calls or tool_calls[-1].get("name") != "ide_finish_task":
        return None
    return await _verified_message(state, state.execution.workspace.ide_summary, agent_name)


async def verified_ide_completion(state, *, agent_name):
    """Детерминированный итог, если модель не смогла оформить краткий отчёт."""
    return await _verified_message(
        state, "Задание выполнено; обязательные проверки результата пройдены.", agent_name
    )


async def _verified_message(state, summary, agent_name):
    execution = state.execution
    client = execution.harness
    if (
        client is None
        or client.failure
        or not summary
        or execution.task_state is None
        or execution.cancelled
        or execution.workspace.unconfirmed
        or execution.task.result(cancelled=False, unconfirmed=False)
        or execution.completion_verifier.evaluate(execution.task_state)["status"] != "completed"
    ):
        return None
    # Local evidence is only a cheap filter. Backend rechecks ownership, Stop,
    # unresolved operations and usage; the report cannot attest to its own success.
    response = await client.exchange(opcode="result")
    result = TaskResultV2.model_validate(response["result"])
    if result.status != "completed":
        return None
    text = ("\n\n" if state.collected.strip() else "") + summary
    state.collected += text
    return AgentEvent(
        type=EventType.STREAM_CHUNK,
        agent_name=agent_name,
        data=text,
        metadata={"model": state.model},
    )
