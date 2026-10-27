"""Продолжение принятого ответа занимает новый slot, а не переигрывает оплаченный."""

from service.shared.harness_protocol import Continuation, HarnessFailure


def restored_length_continuations(execution):
    client = execution.harness
    return client.current.continuation.length_continuations if client is not None else 0


async def advance_model_continuation(state, *, agent_name):
    messages = list(state.round_messages)
    client = state.execution.harness
    if client is not None:
        if client.failure:
            raise HarnessFailure(client.failure)
        from .refinement import propose_refinement, render_refinement

        refinement = await propose_refinement(state)
        if refinement is not None:
            messages.append({"role": "user", "content": render_refinement(refinement.proposal)})
        current = client.current.continuation
        canonical = Continuation(messages=messages, phase="model").conversation()
        if (
            current.phase != "model"
            or current.conversation() != canonical
            or current.length_continuations != state.continuations
        ):
            await client.checkpoint(
                state.execution,
                messages,
                phase="model",
                advance=True,
                agent_name=agent_name,
                length_continuations=state.continuations,
                refinement=refinement,
            )
    # Каждая продолженная часть остаётся отдельным assistant turn. Нельзя снова
    # подставлять объединённый ответ и терять предшествующий continue-запрос.
    state.convo = messages
    state.round_messages = state.convo
    state.segment = ""


def claim_protocol_repair(execution, *, fail_grounding=True):
    state = execution.task_state
    if state is None:
        return True
    if state.protocol_repairs >= 1:
        if fail_grounding:
            execution.grounding.fail(execution.grounding.failure_code)
        return False
    execution.task_state = state.advance(protocol_repairs=state.protocol_repairs + 1)
    return True
