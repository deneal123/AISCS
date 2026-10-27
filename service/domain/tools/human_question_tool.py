"""A local question request. Publication/resume belong to the backend journal."""

import json

from agents import FunctionTool

from service.domain.capabilities.tools.spec import ToolSpec
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.shared.human_question import HumanQuestionError, QuestionPrompt

NAME = "ask_user_question"


async def ask_user_question(ctx, raw: str):
    del ctx
    from service.domain.execution.context import require_current_execution

    execution = require_current_execution()
    try:
        if (
            not execution.policy.flag("human_questions_enabled")
            or execution.cancelled
            or execution.question.prompt is not None
        ):
            raise HumanQuestionError()
        prompt = QuestionPrompt.parse(json.loads(raw))
    except (ValueError, TypeError, HumanQuestionError):
        return ToolCallOutcome(
            '{"error":"invalid_human_question"}',
            "failed",
            0.0,
            retryable=False,
            billable=False,
            failure_code=ToolFailureCode.INVALID_ARGUMENTS,
        )
    execution.question.prompt = prompt
    return '{"awaiting_user":true}'


TOOL = FunctionTool(
    name=NAME,
    description=(
        "Уточни одно существенное решение, без которого нельзя продолжить задачу. "
        "Сначала используй доступные исходники; ясные задания выполняй без опроса. "
        "Дай 2–3 варианта или пустой список для свободного ответа. Собственный текст "
        "доступен всегда. Вызывай отдельно, без других инструментов в этой пачке. "
        "После вопроса работа приостанавливается до ответа пользователя."
    ),
    on_invoke_tool=ask_user_question,
    params_json_schema={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "description": "Один существенный вопрос пользователю.",
            },
            "choices": {
                "type": "array",
                "maxItems": 3,
                "description": "Варианты ответа; пустой список разрешает свободный ответ.",
                "items": {
                    "type": "object",
                    "description": "Один вариант ответа пользователя.",
                    "properties": {
                        "id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 32,
                            "description": "Стабильный идентификатор варианта ответа.",
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 120,
                            "description": "Краткий текст варианта ответа.",
                        },
                    },
                    "required": ["id", "label"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["prompt", "choices"],
        "additionalProperties": False,
    },
)
SPEC = ToolSpec(
    name=NAME,
    tool=TOOL,
    requires_context_attr="human_questions_enabled",
    enabled_field="workspace_enabled",
    concurrency_group="workspace",
    selector_hint=TOOL.description,
)
SPECS = [SPEC]
