"""Command tools use the backend-owned console, never a sidecar shell."""

import json
from uuid import UUID, uuid5

from agents import FunctionTool

from service.domain.capabilities.tools.spec import EFFECT_WORKSPACE_MUTATION, ToolSpec
from service.domain.execution.context import require_current_execution
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools.ide.command_validation import command_arguments, invalid_command
from service.domain.tools.ide.observation import observe_command
from service.shared.harness_protocol import EffectIntent, HarnessFailure
from service.shared.task_contract import NONEMPTY_FILE_PATH_PATTERN


def context(*, execute=False):
    execution = require_current_execution()
    if (
        not execution.policy.flag("ide_tools_enabled")
        or execution.harness is None
        or (execute and not execution.policy.flag("ide_command_tools_enabled"))
    ):
        raise HarnessFailure("task_permission_denied")
    return execution, execution.harness


def outcome(execution, client, data):
    execution.task_state = client.current.state
    pending = data["state"] in {"preparing", "ready", "dispatching", "running", "stopping"}
    if data.get("final_revision"):
        execution.workspace.ide_reads.clear()
        execution.workspace.ide_trees.clear()
        execution.workspace.observe(data["final_revision"])
    blocked = (data.get("verification") or {}).get("status") == "blocked"
    if blocked:
        client.failure = client.failure or "verification_unavailable"
    passed = data["state"] == "completed" and not blocked
    return ToolCallOutcome(
        json.dumps(data, ensure_ascii=False),
        "succeeded" if passed or pending else "failed",
        0,
        billable=False,
        pending=pending,
        failure_code=ToolFailureCode.NONE if passed or pending else ToolFailureCode.UNAVAILABLE,
    )


async def run(_ctx, raw):
    execution, client = context(execute=True)
    try:
        spec = command_arguments(raw)
    except ValueError:
        return invalid_command()
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    operation_id = str(
        uuid5(UUID(client.task_id), f"command:{client.current.continuation.next_step}:{canonical}")
    )
    intent = EffectIntent(
        operation_id=operation_id,
        name="ide_run_command",
        action="exec",
        arguments=canonical,
        source_revision=execution.task_state.source_revision,
    )
    prepared = (await client.exchange(opcode="prepare_effect", effect=intent))["operation"]
    if prepared["status"] == "prepared":
        dispatch = await client.exchange(opcode="dispatch_effect", operation_id=operation_id)
        if not dispatch["operation"].get("dispatch_allowed"):
            raise HarnessFailure("operation_unknown")
        try:
            data = await client.command(action="run", operation_id=operation_id, spec=spec)
        except HarnessFailure as error:
            if error.code in {"verification_unavailable", "usage_limit_exceeded"}:
                client.failure = error.code
                raise
            if error.code == "harness_request_invalid":
                await client.load()
                return invalid_command()
            if error.code != "checkpoint_unavailable":
                raise
            data = await client.command(action="status", operation_id=operation_id)
    else:
        data = await client.command(action="status", operation_id=operation_id)
    # Polling is executor observation, not a new paid model/tool round.
    data = await observe_command(execution, client, operation_id, data)
    return outcome(execution, client, data)


async def status(_ctx, raw):
    execution, client = context()
    operation_id = str(UUID(json.loads(raw)["operation_id"]))
    data = await client.command(action="status", operation_id=operation_id)
    return outcome(execution, client, data)


TOOLS = [
    FunctionTool(
        name="ide_run_command",
        # SDK strict conversion makes every optional property required. This
        # provider-neutral recipe has mutually exclusive fields; the closed
        # schema plus CommandSpec validation remain authoritative on both sides.
        strict_json_schema=False,
        description=(
            "Запустить команду в выбранном проекте после сохранённого снимка. Для проверки "
            "Укажи criterion_id=verify_project и рецепт python_script с expected_stdout, "
            "unittest или установленный pytest. Зависимости не устанавливаются. Исправь "
            "исходник и повтори тот же рецепт; обычный shell не подтверждает задачу. "
            'Пример: {"profile":"python_script","target":"hello_world.py",'
            '"expected_stdout":"hello world","timeout_sec":10,"criterion_id":"verify_project"}. '
            "Для проверки полностью опусти поле command: не передавай shell-команду, "
            "пустую строку или строку null."
        ),
        on_invoke_tool=run,
        params_json_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "profile": {
                    "type": "string",
                    "description": "Профиль запуска команды или проверки проекта.",
                    "enum": ["shell", "python_script", "unittest", "pytest"],
                },
                "target": {
                    "type": "string",
                    "nullable": True,
                    "pattern": NONEMPTY_FILE_PATH_PATTERN,
                    "minLength": 1,
                    "description": "Путь скрипта/тестов. Для shell опусти поле target.",
                },
                "command": {
                    "type": "string",
                    "nullable": True,
                    "description": "Только для shell. Для проверки полностью опусти это поле.",
                },
                "expected_stdout": {
                    "type": "string",
                    "nullable": True,
                    "description": "Ожидаемый stdout скрипта; null, если не задан.",
                },
                "timeout_sec": {
                    "type": "integer",
                    "description": "Максимальное время команды в секундах.",
                    "minimum": 1,
                    "maximum": 120,
                },
                "criterion_id": {
                    "type": "string",
                    "nullable": True,
                    "description": "verify_project для проверки; null для обычной команды.",
                },
            },
            # Conditional requirements belong to the strict recipe validator.
            # Requiring mutually exclusive fields forces meaningless null values.
            "required": ["profile"],
        },
    ),
    FunctionTool(
        name="ide_command_status",
        description=("Прочитать состояние команды по operation_id. Не запускает её снова."),
        on_invoke_tool=status,
        params_json_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operation_id": {
                    "type": "string",
                    "description": "Идентификатор ранее запущенной команды.",
                }
            },
            "required": ["operation_id"],
        },
    ),
]
SPECS = [
    ToolSpec(
        name=tool.name,
        tool=tool,
        enabled_field="workspace_enabled",
        requires_context_attr=(
            "ide_command_tools_enabled" if tool.name == "ide_run_command" else "ide_tools_enabled"
        ),
        source="workspace",
        effect=EFFECT_WORKSPACE_MUTATION,
        concurrency_group="workspace",
        dedup_safe=False,
        default_timeout_sec=240,
        result_limit_chars=24000,
        selector_hint=tool.description,
    )
    for tool in TOOLS
]
