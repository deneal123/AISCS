"""Journal trusted IDE/PDF adapters, not model assertions or arbitrary MCP effects."""

from uuid import UUID, uuid5

from service.domain.capabilities.tools.harness import (
    CONTROL,
    WRITES,
    tool_action,
    unavailable_reason,
)
from service.domain.execution.context import require_current_execution
from service.domain.runners.tool_runtime.contracts import ToolCallOutcome
from service.domain.tools.documents.proposals import restore_review_reference
from service.shared.harness_protocol import (
    CallReceipt,
    EffectIntent,
    EffectResult,
    HarnessFailure,
    PaidCall,
)
from service.shared.task_contract import TaskEvidence, digest_payload


def _evidence(execution, call, operation_id, outcome):
    if not outcome.succeeded or execution.workspace.unconfirmed:
        return []
    path = call.arguments.get("path", "")
    read = (
        execution.workspace.ide_trees
        if call.name == "ide_list_files"
        else execution.workspace.ide_reads
    ).get(path)
    written = execution.workspace.ide_writes.get(path)
    kind = "file" if call.name in WRITES else "read"
    digest = (
        written
        if kind == "file"
        else (read.get("digest") if read and read.get("whole") is True else None)
    )
    if not digest:
        return []
    return [
        TaskEvidence(
            criterion_id=criterion.criterion_id,
            operation_id=operation_id,
            kind=kind,
            target=path,
            digest=digest,
            outcome="passed",
            source_revision=execution.task_state.source_revision,
        )
        for criterion in execution.task_contract.criteria
        if criterion.kind == kind and (not criterion.target or criterion.target == path)
    ]


async def execute_harness_tool(call, invoke):
    execution = require_current_execution()
    client = execution.harness
    if client is None:
        return await invoke()
    if client.failure:
        raise HarnessFailure(client.failure)
    contract = execution.task_contract
    if unavailable_reason(
        client.current.admission, call.name, actions=contract.actions if contract else None
    ):
        raise HarnessFailure("task_permission_denied")
    if call.name in CONTROL:
        return await invoke()
    action = tool_action(call.name)
    state = execution.task_state
    operation_id = str(
        uuid5(
            UUID(client.task_id),
            f"tool:{client.current.continuation.next_step}:{call.call_id}:{call.cache_key}",
        )
    )
    intent = EffectIntent(
        operation_id=operation_id,
        name=call.name,
        action=action,
        arguments=call.canonical_arguments,
        source_revision=state.source_revision,
    )
    result = await client.exchange(opcode="prepare_effect", effect=intent)
    operation = result["operation"]
    if operation["status"] in {"succeeded", "failed"}:
        receipt = EffectResult.model_validate(operation["receipt"])
        additional = [
            item for item in receipt.evidence if item not in execution.task_state.evidence
        ]
        if additional:
            execution.task_state = execution.task_state.advance(
                evidence=[*execution.task_state.evidence, *additional]
            )
        if receipt.status == "succeeded":
            restore_review_reference(execution, call.name, receipt.text)
        return ToolCallOutcome(receipt.text, receipt.status, 0, billable=False)
    if operation["status"] != "prepared":
        raise HarnessFailure("operation_unknown")
    fee_id = str(uuid5(UUID(operation_id), "billing"))
    fee = PaidCall(
        operation_id=fee_id,
        provider="local",
        model="workspace_tool",
        prompt=0,
        completion=0,
        request_digest=digest_payload(intent.model_dump(mode="json")),
        kind="tool",
        billing_tool="workspace_tool",
    )
    await client.exchange(opcode="grant", call=fee)
    fee_dispatch = await client.exchange(opcode="dispatch", operation_id=fee_id)
    if not fee_dispatch["operation"].get("dispatch_allowed"):
        raise HarnessFailure("operation_unknown")
    dispatched = await client.exchange(opcode="dispatch_effect", operation_id=operation_id)
    if not dispatched["operation"].get("dispatch_allowed"):
        raise HarnessFailure("operation_unknown")
    try:
        result = await invoke()
        if not isinstance(result, ToolCallOutcome):
            # A legacy string cannot prove success or even prove absence of an
            # effect. Keep the intent unresolved instead of billing/grounding it.
            raise HarnessFailure("unsupported_adapter")
        outcome = result
        evidence = _evidence(execution, call, operation_id, outcome)
        unknown = execution.workspace.unconfirmed
        status = "unknown" if unknown else "succeeded" if outcome.succeeded else "failed"
        receipt = EffectResult(
            operation_id=operation_id,
            status=status,
            text=outcome.text,
            evidence=evidence,
            charged=None if unknown else outcome.charged,
        )
        acknowledged = await client.exchange(opcode="effect_receipt", effect_result=receipt)
        await client.exchange(
            opcode="call_receipt",
            receipt=CallReceipt(
                operation_id=fee_id,
                status="unknown" if unknown else "succeeded" if outcome.charged else "waived",
            ),
        )
        if unknown:
            client.failure = "operation_unknown"
        if "snapshot" in acknowledged:
            execution.task_state = client.current.state
        elif evidence:
            execution.task_state = execution.task_state.advance(
                evidence=[*execution.task_state.evidence, *evidence]
            )
        return outcome
    except BaseException:
        client.failure = client.failure or "operation_unknown"
        raise
