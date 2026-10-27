"""Предварительная семантика контракта для прежней единственной protocol repair."""

from service.shared.task_contract import TARGET_PATTERN as TARGET_PATTERN


def require_criteria(proposal, surface):
    kinds = {item.kind for item in proposal.criteria}
    allowed = {"read", "file", "command"} if surface == "ide" else {"read", "pdf"}
    required = {"analysis": "read", "change": "file", "document": "pdf"}[proposal.kind]
    if (
        not kinds <= allowed
        or required not in kinds
        or (proposal.kind == "analysis" and kinds != {"read"})
    ):
        raise ValueError("contract_criteria_incompatible")
    identities = [item.criterion_id for item in proposal.criteria]
    if len(identities) != len(set(identities)):
        raise ValueError("contract_criteria_duplicate")


def require_document_target(proposal, project_path):
    if project_path and any(
        item.kind == "pdf" and item.target not in {"", project_path} for item in proposal.criteria
    ):
        raise ValueError("contract_document_target")
