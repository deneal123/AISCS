"""Install backend authority before routing; seal model-proposed criteria before tools."""

from service.application.harness.proposal import (
    CONTRACT_FUNCTION,
    clarification_review_messages,
    contract_messages,
    contract_tool,
    parse_proposal,
    repair_messages,
    response_arguments,
)
from service.domain.execution.model import invoke_model_call
from service.domain.llm_response import first_message_content
from service.infrastructure.harness.client import HarnessClient
from service.shared.harness_protocol import HarnessFailure


async def install_harness(execution):
    reference = (execution.resources.workspace_ref or {}).get("harness_ref")
    if reference is None:
        return
    client = HarnessClient(reference)
    execution.harness = client
    current = await client.load()
    from service.infrastructure.harness.call_payload import require_replay_codec

    require_replay_codec(current.continuation)
    if current.continuation.clarification is not None:
        from service.application.harness.clarification import restore_answer

        restore_answer(execution, current.continuation.clarification)
    for usage in current.usage:
        execution.usage.record_usage(
            {"prompt": usage.prompt, "completion": usage.completion},
            provider=usage.provider,
            model=usage.model,
            kind=usage.kind,
            receipt_id=usage.receipt_id,
        )
    if current.state is not None:
        execution.bind_task_state(current.state)
        # A resumed write receipt proves the past effect, not the current bytes.
        # Restore the readback obligations as well as the completion evidence.
        for evidence in current.state.evidence:
            if evidence.kind == "file" and evidence.outcome == "passed":
                execution.workspace.ide_writes[evidence.target] = evidence.digest
    binding = current.continuation.provider
    if binding:
        from service.domain.client.protocol import PinSource

        execution.provider_session.pin(
            binding.provider, binding.model, source=PinSource.NON_STREAM_RESPONSE
        )
        if binding.state_id:
            execution.provider_session.set_private_state(binding.provider, binding.state_id)


async def admit_harness(execution, model):
    from service.application.harness.result import failure_reply

    try:
        await install_harness(execution)
    except HarnessFailure as error:
        return failure_reply(execution, error.code, model)


async def seal_harness(execution, model):
    client = execution.harness
    if client is None or execution.task_state is not None:
        return
    from service.application.harness.clarification import (
        answered_messages,
        consume_answer,
        park,
        pending,
        restore_question,
    )
    from service.domain.client import create_chat_completion

    answered = answered_messages(execution)
    from service.application.harness.criteria import require_document_target

    reference = getattr(getattr(execution, "resources", None), "workspace_ref", None) or {}
    project_path = (reference.get("document_context") or {}).get("path")
    if pending(execution) and answered is None:
        restore_question(execution)
        return
    messages = answered or contract_messages(client.current.admission, project_path=project_path)
    for attempt in range(2):
        result = await invoke_model_call(
            create_chat_completion,
            model=model,
            kind="meta_usage",
            provider_session=execution.provider_session,
            max_tokens=2048,
            tools=[contract_tool(client.current.admission)],
            tool_choice={"type": "function", "function": {"name": CONTRACT_FUNCTION}},
            messages=messages,
        )
        content = first_message_content(result.response)
        try:
            content = response_arguments(result.response)
            proposal = parse_proposal(content, client.current.admission)
            require_document_target(proposal, project_path)
            from service.settings import config

            if (
                not attempt
                and proposal.needs_clarification
                and config.agents.harness_refinement_enabled
            ):
                messages = clarification_review_messages(messages, content)
                continue
            break
        except ValueError as error:
            if attempt:
                raise HarnessFailure("task_contract_invalid") from None
            messages = repair_messages(messages, content, error=error)
    await client.load()
    if proposal.needs_clarification:
        await park(execution, proposal, messages)
        return
    await client.exchange(
        opcode="seal", expected_revision=client.current.revision, proposal=proposal
    )
    execution.bind_task_state(client.current.state)
    if answered is not None:
        consume_answer(execution, answered)


async def seal_or_block(execution, model):
    from service.application.harness.result import failure_reply

    try:
        await seal_harness(execution, model)
    except HarnessFailure as error:
        return failure_reply(execution, error.code, model)
