"""Private repository context changes file tooling, never paid-tool consent."""

import re
from uuid import UUID


def apply_ide_context(execution):
    target = (execution.resources.workspace_ref or {}).get("ide_context")
    if target is None:
        return False
    if type(target) is not dict or not re.fullmatch(
        r"[a-f0-9]{64}", str(target.get("generation") or "")
    ):
        raise ValueError("invalid_ide_context")
    UUID(str(target.get("repository_id") or ""))
    execution.policy.set_flag("ide_tools_enabled", True)
    execution.policy.set_flag(
        "ide_command_tools_enabled",
        (execution.resources.workspace_ref or {}).get("ide_commands_enabled") is True,
    )
    return True
