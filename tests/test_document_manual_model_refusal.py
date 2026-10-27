"""An unavailable explicit authoring model must not use an admitted alternative."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.subagents import pdf_generation
from service.domain.usage.ledger import UsageLedger
from service.events import EventType


@pytest.mark.asyncio
@pytest.mark.parametrize("qualified", [[], ["openai/gpt-4o"], ["GigaChat-2"]])
async def test_unqualified_manual_model_refuses_before_authoring_or_project(monkeypatch, qualified):
    ledger = UsageLedger()
    execution = SimpleNamespace(usage=ledger)
    intent = AsyncMock(side_effect=AssertionError("authoring_must_not_start"))
    project = AsyncMock(side_effect=AssertionError("project_must_not_be_created"))
    monkeypatch.setattr(pdf_generation, "require_execution", lambda: execution)
    discovery = AsyncMock(return_value=qualified)
    monkeypatch.setattr(pdf_generation, "list_qualified_models", discovery)
    monkeypatch.setattr(pdf_generation, "resolve_document_intent", intent)
    monkeypatch.setattr(pdf_generation, "create_document_project", project)
    agent = pdf_generation.PDFGenerationAgent({})
    monkeypatch.setattr(agent, "preferred_model", lambda: "EmbeddingsGigaR")

    events = [
        event
        async for event in agent.process(
            'Создай PDF с текстом "тест"',
            SimpleNamespace(workspace_ref={"workspace_id": "opaque-test-workspace"}),
        )
    ]

    complete = [event for event in events if event.type == EventType.AGENT_COMPLETE]
    assert len(complete) == 1
    metadata = complete[0].metadata
    assert metadata["document_outcome"] == "failed"
    assert metadata["document_failure_code"] == "selected_model_unavailable"
    assert metadata["requested_authoring_model"] == "EmbeddingsGigaR"
    assert metadata["actual_authoring_model"] is None
    assert not metadata.get("document_project_saved")
    assert ledger.cursor() == 0
    discovery.assert_awaited_once()
    intent.assert_not_awaited()
    project.assert_not_awaited()
