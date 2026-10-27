"""Resume the already accepted tool round, without consuming another round."""

from service.domain.runners.chat.workspace_control import control_gate
from service.shared.harness_protocol import HarnessFailure


async def resume_tool_round(state, execute_tool_round):
    client = state.execution.harness
    if client is None or client.current.continuation.phase != "tools":
        return
    async for event in control_gate(state, agent_name=client.current.continuation.agent_name):
        yield event
    if state.finalizing:
        return
    if not state.convo or not state.convo[-1].get("tool_calls"):
        raise HarnessFailure("provider_state_incompatible")
    message = state.convo.pop()
    calls = [{"id": call["id"], **call["function"]} for call in message["tool_calls"]]
    async for event in execute_tool_round(
        state.convo,
        calls,
        state.tool_index,
        state.tool_ctx,
        message.get("content") or "",
        state.billed,
        round_number=state.execution.task.rounds,
        summary=state.tool_summary,
        cache=state.tool_cache,
        dedup_mode=state.tool_dedup_mode,
    ):
        yield event
    state.round_messages = state.convo
