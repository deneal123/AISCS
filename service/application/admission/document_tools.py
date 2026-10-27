"""Apply backend-derived PDF consent without granting data or provider capabilities."""

from service.domain.execution.context import RunExecutionContext


def apply_document_tool_consent(execution: RunExecutionContext) -> bool:
    target = (execution.resources.workspace_ref or {}).get("document_context")
    approved = bool(
        isinstance(target, dict)
        and target.get("tools_auto_approved") is True
        and target.get("project_id")
        and target.get("path")
        and not execution.policy.flag("confirmation_declined")
    )
    execution.policy.set_flag("document_tools_auto_approved", approved)
    # Editing an explicitly selected PDF must not depend on the general planner
    # guessing files_tool=True. This grants proposals, not legacy source writes.
    execution.policy.set_flag("document_patch_enabled", approved)
    if approved:
        for spec in execution.capabilities.tools.values():
            if spec.confirm_by_default and spec.requires_context_attr:
                execution.policy.set_flag(spec.requires_context_attr, True)
    execution.policy.set_flag(
        "document_structure_enabled",
        approved and type(target.get("patch_version")) is int and target.get("patch_version") == 2,
    )
    return approved
