"""Continue a frozen product task without routing, planning or rebuilding its prompt."""

from service.shared.harness_protocol import HarnessFailure


def has_continuation(execution):
    client = execution.harness
    return client is not None and bool(client.current.continuation.messages)


async def resume_task(processor, user_input, context, execution):
    client = execution.harness
    saved = client.current.continuation
    code = None
    if saved.phase == "waiting_user" and execution.question.resume_json is None:
        code = "user_decision_required"
    elif (
        not saved.agent_name
        or saved.provider is None
        or saved.phase not in {"model", "tools", "waiting_user"}
    ):
        # An old checkpoint without its execution owner cannot safely be rerouted.
        code = "provider_state_incompatible"
    if code:
        client.failure = code
        raise HarnessFailure(code)
    try:
        agent = processor.orchestrator.get_agent(saved.agent_name)
    except (KeyError, ValueError):
        client.failure = "provider_state_incompatible"
        raise HarnessFailure(client.failure) from None
    if agent is None or agent.name != saved.agent_name:
        # The ordinary router may fall back to general; recovery must not.
        client.failure = "provider_state_incompatible"
        raise HarnessFailure(client.failure)
    async for event in agent.process(user_input, context):
        yield event
