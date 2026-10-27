"""Структурное предложение PDF v2; применение остаётся у существующего редактора."""

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.tools.spec import (
    EFFECT_WORKSPACE_MUTATION,
    GROUNDING_WORKSPACE,
    ToolSpec,
)
from service.domain.documents.authoring.protocol import BLOCK_SCHEMA
from service.domain.documents.semantic.review import ReviewProblem
from service.domain.documents.semantic.structure import validate_structure_review
from service.domain.execution.context import require_current_execution
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools.document_proposal_tool import _rejected
from service.domain.tools.documents.proposals import save_review_proposal
from service.domain.tools.workspace.client import call
from service.domain.tools.workspace.specs import BILLING_NAME, ENABLED_FIELD


async def propose_structure(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    execution = require_current_execution()
    reference = execution.resources.workspace_ref or {}
    if not execution.policy.flag("document_structure_enabled"):
        return _rejected("unsupported", ToolFailureCode.POLICY)
    target = reference.get("document_context") or {}
    checked = validate_structure_review(raw, target)
    if isinstance(checked, ReviewProblem):
        code = (
            ToolFailureCode.POLICY
            if checked is ReviewProblem.OUTSIDE_SELECTION
            else ToolFailureCode.INVALID_ARGUMENTS
        )
        if checked is ReviewProblem.DRAFT_UNAVAILABLE:
            code = ToolFailureCode.PROTOCOL
        return _rejected("invalid", code, checked)
    return await save_review_proposal(execution, reference, target, checked.operations, send=call)


def _array(description, items):
    return {"type": "array", "description": description, "items": items, "maxItems": 32}


_ID = {"type": "string", "description": "Точный идентификатор блока текущей структуры."}
_ANCHOR = {
    "type": "string",
    "description": "ID блока, после которого поместить; пустая строка — начало.",
}

tool = FunctionTool(
    name="tex_propose_structure",
    description=(
        "Предложить атомарные замены, удаления, вставки и перестановки PDF-блоков. "
        "Не применяет и не собирает. Сначала замены (replacements), затем удаления (deletions), "
        "вставки (insertions) и перемещения (moves). "
        "Не более 32 операций всего. Новые ID начинаются с new_."
    ),
    params_json_schema={
        "type": "object",
        "description": "Структурная правка выбранной версии для просмотра.",
        "properties": {
            "base_version": {
                "type": "integer",
                "minimum": 1,
                "description": "Точная version текущего черновика.",
            },
            "replacements": _array("Замены существующих блоков без смены ID и типа.", BLOCK_SCHEMA),
            "deletions": _array("Идентификаторы блоков для удаления.", _ID),
            "insertions": _array(
                "Вставки в порядке списка с уникальными временными new_* ID.",
                {
                    "type": "object",
                    "description": "Новый блок и существующий якорь.",
                    "properties": {"after_id": _ANCHOR, "block": BLOCK_SCHEMA},
                    "required": ["after_id", "block"],
                    "additionalProperties": False,
                },
            ),
            "moves": _array(
                "Перемещения блоков после всех вставок.",
                {
                    "type": "object",
                    "description": "Переместить существующий блок без изменения содержания.",
                    "properties": {"block_id": _ID, "after_id": _ANCHOR},
                    "required": ["block_id", "after_id"],
                    "additionalProperties": False,
                },
            ),
        },
        "required": ["base_version", "replacements", "deletions", "insertions", "moves"],
        "additionalProperties": False,
    },
    on_invoke_tool=propose_structure,
)

SPECS = [
    ToolSpec(
        name=tool.name,
        tool=tool,
        requires_context_attr="document_structure_enabled",
        billing_name=BILLING_NAME,
        enabled_field=ENABLED_FIELD,
        source="workspace",
        effect=EFFECT_WORKSPACE_MUTATION,
        concurrency_group="workspace",
        grounding_roles=frozenset({GROUNDING_WORKSPACE}),
        selector_hint="предложить вставку, удаление и перестановку блоков PDF без записи",
    )
]
