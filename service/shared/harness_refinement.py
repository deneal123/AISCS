"""Ограниченная рекомендация Harness²: не полномочия, не инструмент и не evidence."""

from pydantic import Field, field_validator

from service.shared.task_contract import ContractModel, canonical_uuid, immutable_items

PROPOSAL_TOOL = "harness_refine_instructions"


class ToolGuidance(ContractModel):
    name: str = Field(
        pattern=r"^[a-zA-Z0-9_-]{1,64}$", description="Имя уже доступного инструмента."
    )
    advice: str = Field(
        min_length=1,
        max_length=800,
        repr=False,
        description="Краткая подсказка на русском без новых прав.",
    )


class RefinementProposal(ContractModel):
    instruction: str = Field(
        min_length=1,
        max_length=1600,
        repr=False,
        description="Одна конкретная поправка к инструкции на русском.",
    )
    tools: tuple[ToolGuidance, ...] = Field(
        default=(),
        max_length=4,
        repr=False,
        description="Подсказки только к уже разрешённым инструментам.",
    )

    _items = field_validator("tools", mode="before")(immutable_items)


def render_refinement(proposal: RefinementProposal) -> str:
    return (
        "Рекомендация после неудачной попытки; не расширяет полномочия и не является "
        "подтверждением результата. Исходные правила и обязательные проверки сохраняются.\n"
        + proposal.instruction
        + "".join(f"\n{tool.name}: {tool.advice}" for tool in proposal.tools)
    )


def proposal_tool() -> dict:
    schema = RefinementProposal.model_json_schema()
    # GigaChat не принимает $defs/$ref. Разворачиваем единственный известный узел,
    # сохраняя все ограничения, вместо ослабления общего compiler/schema gate.
    guidance = schema.pop("$defs")["ToolGuidance"]
    guidance["description"] = "Подсказка к одному уже разрешённому инструменту."
    schema["properties"]["tools"]["items"] = guidance
    return {
        "type": "function",
        "function": {
            "name": PROPOSAL_TOOL,
            "description": "Предложить ограниченное улучшение инструкции без исполнения действий.",
            "parameters": schema,
        },
    }


class RefinementAttempt(ContractModel):
    baseline_operation: str
    proposal_operation: str
    proposal: RefinementProposal = Field(repr=False)
    probe_step: int = Field(ge=1, le=1024)
    baseline_evidence_count: int = Field(ge=0, le=1024)
    adopted: bool = False

    _ids = field_validator("baseline_operation", "proposal_operation")(canonical_uuid)


def proposal_from_message(message: dict) -> RefinementProposal:
    calls = message.get("tool_calls") or []
    if calls:
        if len(calls) != 1 or calls[0]["function"]["name"] != PROPOSAL_TOOL:
            raise ValueError("refinement_proposal_invalid")
        content = calls[0]["function"]["arguments"]
    else:
        content = message.get("content")
    return RefinementProposal.model_validate_json(content)
