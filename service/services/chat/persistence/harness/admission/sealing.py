"""Backend-owned контракт: критерии модели не выдают прав или подтверждений."""

from service.shared.harness_protocol import HarnessFailure
from service.shared.task_contract import TaskContract, TaskCriterion, TaskState


def sealed_state(current, proposal):
    admission = current.admission
    if proposal.needs_clarification:
        raise HarnessFailure("user_decision_required")
    if proposal.question:
        raise HarnessFailure("task_contract_invalid")
    criteria = list(proposal.criteria)
    if proposal.kind == "change":
        if admission.surface != "ide":
            raise HarnessFailure("task_contract_invalid")
        if any(item.criterion_id == "verify_project" for item in criteria):
            raise HarnessFailure("task_contract_invalid")
        criteria.append(TaskCriterion(criterion_id="verify_project", kind="command"))
    if proposal.kind == "document" and admission.surface != "pdf":
        raise HarnessFailure("task_contract_invalid")
    actions = ("read",) if proposal.kind == "analysis" else admission.actions
    try:
        contract = TaskContract(
            task_id=admission.task_id,
            project_id=admission.project_id,
            generation=admission.generation,
            kind=proposal.kind,
            goal=admission.goal,
            actions=actions,
            criteria=criteria,
            credit_limit=admission.credit_limit,
            active_limit_ms=admission.active_limit_ms,
        )
    except ValueError:
        # Неверные критерии — ошибка контракта, не недоступность PostgreSQL.
        # Validation input с исходной целью не публикуется.
        raise HarnessFailure("task_contract_invalid") from None
    return TaskState(
        contract=contract,
        source_revision=admission.source_revision,
        budget={
            "spent_credits": current.spent_credits,
            "held_credits": current.held_credits,
            "active_ms": current.continuation.admission_active_ms,
        },
    )
