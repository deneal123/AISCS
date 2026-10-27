"""Выдача и dispatch используют один закрытый список адаптеров durable harness."""

from service.domain.capabilities.tools.spec import TASK_POLICY, Omission, ToolSet

READS = frozenset({"ide_list_files", "ide_read_file"})
WRITES = frozenset({"ide_write_file", "ide_edit_file", "ide_create_directory"})
PROPOSALS = frozenset({"tex_propose_patch", "tex_propose_structure"})
CONTROL = frozenset(
    {"ide_finish_task", "ask_user_question", "ide_run_command", "ide_command_status"}
)


def tool_action(name):
    if name in READS:
        return "read"
    if name in WRITES:
        return "write"
    if name in PROPOSALS:
        return "document"
    if name in {"ide_run_command", "ide_command_status"}:
        return "exec"
    return None


def unavailable_reason(admission, name, *, actions=None):
    supported = (
        READS | WRITES | CONTROL
        if admission.surface == "ide"
        else PROPOSALS | {"ask_user_question"}
    )
    if name not in supported:
        return "Нет проверяемого адаптера для этого типа задания."
    action = tool_action(name)
    allowed = set(admission.actions)
    if actions is not None:
        allowed.intersection_update(actions)
    if action and action not in allowed:
        return "Действие не разрешено контрактом задания."
    return None


def restrict_toolset(toolset, execution):
    if execution is None or execution.harness is None:
        return toolset
    admission = execution.harness.current.admission
    contract = execution.task_contract
    tools, omissions = [], list(toolset.omissions)
    for tool in toolset.tools:
        name = str(getattr(tool, "name", ""))
        reason = unavailable_reason(admission, name, actions=contract.actions if contract else None)
        if reason:
            omissions.append(Omission(name, TASK_POLICY, reason))
        else:
            tools.append(tool)
    return ToolSet(tools=tools, omissions=omissions)
