"""Review-only patch capability. No source write, compilation or publication."""

from __future__ import annotations

import json

from agents import FunctionTool, RunContextWrapper

from service.domain.capabilities.tools.spec import (
    EFFECT_WORKSPACE_MUTATION,
    GROUNDING_WORKSPACE,
    ToolSpec,
)
from service.domain.documents.authoring.protocol import BLOCK_SCHEMA
from service.domain.documents.semantic.review import ReviewProblem, validate_review_patch
from service.domain.execution.context import require_current_execution
from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.domain.tools.documents.proposals import save_review_proposal
from service.domain.tools.workspace.client import call
from service.domain.tools.workspace.specs import BILLING_NAME, ENABLED_FIELD


def _rejected(
    status: str, code: ToolFailureCode, problem: ReviewProblem | None = None
) -> ToolCallOutcome:
    return ToolCallOutcome(
        json.dumps(
            {
                "status": status,
                **({"error_code": problem.value, "message": problem.message} if problem else {}),
            },
            ensure_ascii=False,
        ),
        "invalid" if code == ToolFailureCode.INVALID_ARGUMENTS else "failed",
        0.0,
        retryable=code in {ToolFailureCode.INVALID_ARGUMENTS, ToolFailureCode.CONFLICT},
        billable=False,
        failure_code=code,
    )


async def propose_document_patch(ctx: RunContextWrapper, raw: str) -> ToolCallOutcome:
    del ctx
    execution = require_current_execution()
    ref = execution.resources.workspace_ref or {}
    target = ref.get("document_context") or {}
    checked = validate_review_patch(raw, target)
    if isinstance(checked, ReviewProblem):
        if checked is ReviewProblem.DRAFT_UNAVAILABLE:
            return _rejected("unavailable", ToolFailureCode.PROTOCOL, checked)
        code = (
            ToolFailureCode.POLICY
            if checked is ReviewProblem.OUTSIDE_SELECTION
            else ToolFailureCode.INVALID_ARGUMENTS
        )
        status = "outside_selection" if code is ToolFailureCode.POLICY else "invalid"
        return _rejected(status, code, checked)
    return await save_review_proposal(
        execution,
        ref,
        target,
        {"base_version": checked.patch.base_version, "replacements": checked.replacements},
        send=call,
    )


tool = FunctionTool(
    name="tex_propose_patch",
    description="Предложить правки блоков PDF для просмотра. Не меняет исходники.",
    params_json_schema={
        "type": "object",
        "description": "Версионированные замены для просмотра, без изменения исходников.",
        "properties": {
            "base_version": {
                "type": "integer",
                "minimum": 1,
                "description": "Текущая версия черновика.",
            },
            "replacements": {
                "type": "array",
                "description": "Семантические блоки для замены.",
                "items": BLOCK_SCHEMA,
                "minItems": 1,
                "maxItems": 32,
            },
        },
        "required": ["base_version", "replacements"],
        "additionalProperties": False,
    },
    on_invoke_tool=propose_document_patch,
)

SPECS = [
    ToolSpec(
        name=tool.name,
        tool=tool,
        requires_context_attr="document_patch_enabled",
        billing_name=BILLING_NAME,
        enabled_field=ENABLED_FIELD,
        source="workspace",
        effect=EFFECT_WORKSPACE_MUTATION,
        concurrency_group="workspace",
        grounding_roles=frozenset({GROUNDING_WORKSPACE}),
        selector_hint="предложить точечные изменения открытого PDF без записи исходников",
    )
]
