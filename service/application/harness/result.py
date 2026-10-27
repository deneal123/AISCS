"""Closed task outcome projection; transport completion is not task success."""

from service.shared.task_contract import CompletionVerifier, TaskResultV2


def failure_projection(execution, code):
    if execution.task_state is not None:
        result = CompletionVerifier.evaluate(execution.task_state)
    else:
        result = {
            "schema_version": 2,
            "confirmed": [],
            "unchecked": ["contract"],
            "references": [],
            "rounds": execution.task.rounds,
            "repair_cycles": execution.task.repairs,
        }
    result.update(
        status="cancelled" if code == "cancelled" else "blocked", verified=False, blocker=code
    )
    return TaskResultV2.model_validate(result).model_dump(mode="json")


def failure_reply(execution, code, model):
    from service.application.harness.messages import failure_message
    from service.application.reply_assembler import ReplyAssembler
    from service.application.use_cases.agent_execution_use_cases import PersistSessionHistoryUseCase

    assembler = ReplyAssembler(execution.usage)
    assembler.finalize_usage()
    return PersistSessionHistoryUseCase().execute(
        reply=failure_message(code),
        metadata={
            "execution_status": "partial",
            "task_result": failure_projection(execution, code),
        },
        resolved_model=model or "",
        reply_assembler=assembler,
    )


async def finalize_harness(execution, metadata):
    client = execution.harness
    if client is None:
        return
    code = "cancelled" if execution.cancelled else client.failure
    guard = execution.task.result(
        cancelled=execution.cancelled, unconfirmed=execution.workspace.unconfirmed
    )
    if guard and not code:
        code = guard["blocker"]
    if code:
        result = failure_projection(execution, code)
    else:
        try:
            response = await client.exchange(opcode="result")
            result = response.get("result") or failure_projection(
                execution, "task_contract_invalid"
            )
        except Exception:
            result = failure_projection(execution, "checkpoint_unavailable")
    metadata["task_result"] = TaskResultV2.model_validate(result).model_dump(mode="json")
    if result["status"] != "completed" and metadata.get("execution_status") == "completed":
        metadata["execution_status"] = "partial"
