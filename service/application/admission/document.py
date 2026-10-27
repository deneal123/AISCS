"""Project-free terminal result for a rejected manual PDF authoring model."""

from typing import Any

from service.application.reply_assembler import ReplyAssembler
from service.application.use_cases.agent_execution_use_cases import (
    PersistSessionHistoryUseCase,
    RouteModelUseCase,
)
from service.domain.documents.run_outcome import (
    DocumentRunOutcome,
    DocumentStage,
    document_status_event,
)
from service.domain.execution.context import RunExecutionContext
from service.domain.routing.explicit_intent import explicit_requested_tool
from service.domain.routing.policy import canonical_route
from service.domain.tools.router import SelectedModelUnavailable


async def resolve_execution_model(
    *,
    text: str,
    selected_model: str | None,
    input_type: Any,
    route_override: str | None,
    resolved_category: str | None,
    execution: RunExecutionContext,
    on_event: Any,
) -> tuple[str | None, dict[str, Any]] | dict[str, Any]:
    if execution.harness is not None:
        binding = execution.harness.current.continuation.provider
        if binding is not None:
            # Recovery continues the frozen provider conversation. Routing the
            # original goal again is neither a new task nor a model choice.
            return binding.model, {}
    try:
        return await RouteModelUseCase().execute(
            text=text, selected_model=selected_model, input_type=input_type, execution=execution
        )
    except SelectedModelUnavailable:
        requested_route = canonical_route(
            route_override or resolved_category or explicit_requested_tool(text)
        )
        if requested_route != "pdf_gen":
            raise
        return document_model_refusal(execution, selected_model, on_event)


def document_model_refusal(
    execution: RunExecutionContext,
    requested_model: str | None,
    on_event: Any,
) -> dict[str, Any]:
    event = document_status_event(
        "pdf_gen",
        DocumentStage.INTENT,
        "failed",
        outcome=DocumentRunOutcome.FAILED,
        failure_code="selected_model_unavailable",
    )
    if on_event is not None:
        on_event(event)
    assembler = ReplyAssembler(execution.usage)
    assembler.finalize_usage()
    metadata = {
        **event.metadata,
        "execution_status": "failed",
        "requested_authoring_model": requested_model,
        "actual_authoring_model": None,
        "document_project_saved": False,
    }
    return PersistSessionHistoryUseCase().execute(
        reply=(
            "Выбранная модель сейчас недоступна для подготовки документа. "
            "Другая модель не была подставлена."
        ),
        metadata=metadata,
        resolved_model=requested_model or "",
        reply_assembler=assembler,
        workspace_artifacts=[],
    )
