"""Small, local terminal report; the tool makes no LLM request and is not a write receipt."""

from __future__ import annotations

import json

from agents import FunctionTool

from service.domain.capabilities.tools.spec import ToolSpec
from service.domain.execution.context import RunExecutionContext, require_current_execution
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode

MAX_SUMMARY = 280


def valid_summary(value: object) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= MAX_SUMMARY
        and value == value.strip()
        and not any(ord(char) < 32 or ord(char) == 127 or char in "\u2028\u2029" for char in value)
    )


async def ide_finish_task(ctx, raw: str):
    del ctx
    execution = require_current_execution()
    try:
        args = json.loads(raw)
        if (
            not isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict)
            or type(args) is not dict
            or set(args) != {"summary", "outcome"}
            or not valid_summary(args["summary"])
            or args["outcome"] not in ("changed", "unchanged", "blocked")
        ):
            raise ValueError
    except (ValueError, TypeError):
        return ToolCallOutcome(
            '{"error":"invalid_ide_summary"}',
            "failed",
            0.0,
            retryable=False,
            billable=False,
            failure_code=ToolFailureCode.INVALID_ARGUMENTS,
        )
    if (
        args["outcome"] == "changed"
        and (not execution.workspace.ide_writes or execution.workspace.ide_unconfirmed)
    ) or (args["outcome"] == "unchanged" and execution.workspace.ide_writes):
        return ToolCallOutcome(
            json.dumps(
                {
                    "error": "ide_result_not_confirmed",
                    "instruction": (
                        "Итог не создаёт файлы. Для изменения проекта сначала выполни "
                        "ide_write_file/ide_edit_file и получи подтверждение. Если работа "
                        "заблокирована, укажи outcome=blocked и честную причину; не повторяй "
                        "запись с потерянным подтверждением."
                    ),
                },
                ensure_ascii=False,
            ),
            "failed",
            0.0,
            retryable=False,
            billable=False,
            failure_code=ToolFailureCode.INVALID_ARGUMENTS,
        )
    execution.workspace.ide_summary = args["summary"]
    return '{"summary_recorded":true}'


def summary_for_result(execution: RunExecutionContext, *, task_result: dict | None = None) -> str:
    """Safe degradation if the model could not supply the required terminal report."""
    if execution.workspace.ide_unconfirmed:
        return "Результат записи не подтверждён. Проверьте файлы перед повторной правкой."
    if (
        task_result
        and task_result.get("schema_version") == 2
        and (task_result.get("status") != "completed" or task_result.get("verified") is not True)
    ):
        return "Задание не завершено: подтверждённый результат и блокер указаны в статусе задания."
    if execution.workspace.ide_summary:
        return execution.workspace.ide_summary
    if task_result and task_result.get("schema_version") == 2:
        return "Задание выполнено; обязательные проверки результата пройдены."
    count = len(execution.workspace.ide_writes)
    if count:
        return f"Подтверждено записей в среду: {count}. Изменения не закоммичены."
    return "Агент не передал краткий итог. Откройте ответ в чате или продолжите запрос здесь."


TOOL = FunctionTool(
    name="ide_finish_task",
    description=(
        "Последним действием подведи итог запроса IDE: 1–2 коротких предложения, до 280 символов, "
        "одной строкой, без Markdown, кода и секретов. Передай смысл последнего ответа: "
        "результат, причину невыполненного и следующий шаг или вопрос. "
        "outcome=changed допустим только после подтверждённой записи; unchanged — для ответа "
        "без изменений; blocked — при препятствии. Этот инструмент НЕ создаёт файлы. "
        "Не заявляй о записях, проверках или коммитах без подтверждения. Не запускает код или LLM."
    ),
    on_invoke_tool=ide_finish_task,
    params_json_schema={
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["changed", "unchanged", "blocked"],
                "description": "Подтверждённый исход: правки, ответ без правок или препятствие.",
            },
            "summary": {
                "type": "string",
                "minLength": 1,
                "maxLength": MAX_SUMMARY,
                "description": "Краткий итог для панели IDE.",
            },
        },
        "required": ["summary", "outcome"],
        "additionalProperties": False,
    },
)
SPEC = ToolSpec(
    name=TOOL.name,
    tool=TOOL,
    requires_context_attr="ide_tools_enabled",
    enabled_field="workspace_enabled",
    concurrency_group="workspace",
    selector_hint=TOOL.description,
)
