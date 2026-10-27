"""The production execution boundary preserves a PDF qualification refusal."""

import pytest

from service.application.agent_execution_service import DefaultAgentExecutionService
from service.application.use_cases.agent_execution_use_cases import RouteModelUseCase
from service.domain.tools.router import SelectedModelUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["pdf_gen", "pptx_gen", None])
@pytest.mark.parametrize("model", ["EmbeddingsGigaR", "gpthub-unavailable-manual-chat"])
async def test_pdf_manual_refusal_returns_terminal_before_project_or_model_call(
    monkeypatch, route, model
):
    async def initialize(_execution):
        pass

    async def refused(_self, **_kwargs):
        raise SelectedModelUnavailable("private-provider-body-marker")

    monkeypatch.setattr(
        "service.domain.client.registry.initialize_run_provider_admission", initialize
    )
    monkeypatch.setattr(RouteModelUseCase, "execute", refused)
    events = []
    result = await DefaultAgentExecutionService().execute(
        text="Создай PDF с текстом тест",
        thread_id="test-thread",
        user_id="test-owner",
        session_data=None,
        selected_model=model,
        route_override=route,
        input_type="text",
        web_search=False,
        deep_research=False,
        file_context="",
        on_event=events.append,
    )
    assert result["metadata"]["document_outcome"] == "failed"
    assert result["metadata"]["document_failure_code"] == "selected_model_unavailable"
    assert result["metadata"]["execution_status"] == "failed"
    assert result["metadata"]["requested_authoring_model"] == model
    assert result["metadata"]["actual_authoring_model"] is None
    assert result["metadata"]["document_project_saved"] is False
    assert result["per_call_usage"] == []
    assert result["total_tokens"] == 0
    assert result["workspace_artifacts"] == []
    assert len(events) == 1
    assert events[0].metadata["document_status"]["failure_code"] == "selected_model_unavailable"
    assert "private-provider-body-marker" not in str(result) + str(events)
