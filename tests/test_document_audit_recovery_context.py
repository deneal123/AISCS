"""An audit status refresh must not erase the saved authoring project."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents import normalize_brief
from service.domain.subagents import pdf_generation_runtime as runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["passed", "retryable", "failed"])
async def test_audit_refresh_preserves_project_and_correct_failure_stage(monkeypatch, outcome):
    run = runtime.DocumentGenerationRun(
        ref={},
        brief=normalize_brief('Создай PDF с текстом "тест"'),
        model="qualified-authoring-model",
        project_path="document-test",
        scaffold_source="",
    )
    audit = SimpleNamespace(
        passed=outcome == "passed",
        retryable=outcome == "retryable",
        status="visual_pending",
    )
    refreshed = (
        {"state": "ready", "build_id": "test-build"}
        if outcome == "passed"
        else {"state": "failed", "failure_code": "visual_audit_failed"}
    )
    monkeypatch.setattr(runtime, "audit_document_build", AsyncMock(return_value=audit))
    monkeypatch.setattr(runtime, "call", AsyncMock(return_value=refreshed))
    result, may_repair = await run._resolve_visual_audit(
        {"state": "visual_pending", "build_id": "test-build", "stage": "compile"},
        execution=object(),
    )
    assert result["project_saved"] is True
    assert result["stage"] == "visual_audit"
    assert result["build_id"] == "test-build"
    assert may_repair is (outcome == "passed")
    if outcome == "failed":
        code, stage, retryable = runtime.public_failure(result)
        assert code == "visual_audit_failed"
        assert stage.value == "visual_audit"
        assert retryable is False
