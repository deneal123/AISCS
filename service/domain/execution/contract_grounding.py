"""Связь доверенного контракта чтения с существующим ограничителем ответа."""

from service.domain.execution.context import GroundingRequirement, RunExecutionContext

CONTRACT_READ_TOOLS = frozenset({"ide_read_file", "ide_list_files"})


def require_contract_read(execution: RunExecutionContext) -> None:
    state = execution.task_state
    if (
        execution.harness is None
        or state is None
        or state.contract.kind != "analysis"
        or state.cancelled
        or execution.cancelled
        or not isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict)
        or execution.policy.grounding_reason is not GroundingRequirement.NONE
    ):
        return
    unchecked = set(execution.completion_verifier.evaluate(state)["unchecked"])
    if not any(
        item.kind == "read" and item.criterion_id in unchecked for item in state.contract.criteria
    ):
        return
    # Только обязанность выполнить уже разрешённое чтение. Ни полномочий, ни
    # evidence здесь не появляется: актуальную версию подтверждает backend receipt.
    execution.policy.set_flag("contract_read_required", True)
    execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
