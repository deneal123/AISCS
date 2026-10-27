"""Freeze only completed tool history at the human boundary; never poll an LLM."""

from service.events import AgentEvent, EventType
from service.shared.human_question import HumanQuestionError, freeze_question_continuation


def freeze_pause(state, tool_calls) -> bool:
    question = state.execution.question
    if question.prompt is None:
        return False
    if state.execution.cancelled:
        question.prompt = None
        return True
    try:
        if len(tool_calls) != 1 or tool_calls[0].get("name") != "ask_user_question":
            raise HumanQuestionError()
        question.continuation_json = freeze_question_continuation(
            {
                "model": state.model,
                "messages": state.convo,
                "tool_call_id": tool_calls[0].get("id"),
            },
            question.prompt,
        )
    except HumanQuestionError:
        question.failed = True
    state.segment = ""
    return True


async def checkpoint_question_pause(state, tool_calls, *, agent_name):
    """Stop имеет приоритет перед фиксацией ожидания ответа пользователя."""
    from service.domain.runners.chat.workspace_control import workspace_safe_boundary

    execution = state.execution
    async for event in workspace_safe_boundary(state, agent_name=agent_name):
        if isinstance(event, bool):
            if event:
                execution.question.prompt = None
                return
        else:
            yield event
    if freeze_pause(state, tool_calls) and execution.harness is not None:
        await execution.harness.checkpoint(execution, state.convo, phase="waiting_user")


def question_boundary_event(execution, *, agent_name, usage):
    if execution.question.waiting:
        return AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=agent_name,
            data="Ожидаю уточнения пользователя.",
            metadata={"kind": "human_question_pending", "token_usage": usage},
        )
    return AgentEvent(
        type=EventType.ERROR,
        agent_name=agent_name,
        metadata={
            "failure_code": "payload",
            "category": "internal",
            "retryable": False,
            "token_usage": usage,
        },
    )
