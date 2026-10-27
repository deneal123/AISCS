"""Malformed workspace claims cannot reach a provider or invent an attestation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.documents import visual_audit as audit


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [True, 1.5, "1", "PRIVATE_MARKER", float("inf"), {}, None])
async def test_page_count_requires_an_exact_integer(monkeypatch, caplog, count):
    monkeypatch.setattr(audit, "require_execution", lambda value: value)
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": count,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                }
            }
        ),
    )
    models = AsyncMock(return_value=["vision-model"])
    provider = AsyncMock()
    report = AsyncMock()
    monkeypatch.setattr(audit, "list_qualified_models", models)
    monkeypatch.setattr(audit, "invoke_model_call", provider)
    monkeypatch.setattr(audit, "_report", report)
    result = await audit.audit_document_build({}, "fixture-build", execution=SimpleNamespace())
    assert result.status == "invalid" and not result.passed
    models.assert_not_awaited()
    provider.assert_not_awaited()
    report.assert_not_awaited()
    assert "PRIVATE_MARKER" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["source_digest", "artifact_sha256"])
@pytest.mark.parametrize("value", [None, {"private": "PRIVATE_MARKER"}, "PRIVATE_MARKER", "A" * 64])
async def test_invalid_provenance_cannot_start_a_paid_audit(monkeypatch, caplog, field, value):
    claim = {"page_count": 1, "source_digest": "a" * 64, "artifact_sha256": "b" * 64}
    claim[field] = value
    monkeypatch.setattr(audit, "require_execution", lambda context: context)
    monkeypatch.setattr(audit, "call", AsyncMock(return_value={"audit": claim}))
    models = AsyncMock()
    report = AsyncMock()
    monkeypatch.setattr(audit, "list_qualified_models", models)
    monkeypatch.setattr(audit, "_report", report)
    result = await audit.audit_document_build({}, "fixture-build", execution=SimpleNamespace())
    assert result.status == "invalid" and not result.passed
    models.assert_not_awaited()
    report.assert_not_awaited()
    assert "PRIVATE_MARKER" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, audit.MAX_PAGES + 1])
async def test_valid_provenance_outside_page_budget_gets_only_a_bounded_limit(monkeypatch, count):
    claim = {"page_count": count, "source_digest": "a" * 64, "artifact_sha256": "b" * 64}
    monkeypatch.setattr(audit, "require_execution", lambda context: context)
    monkeypatch.setattr(audit, "call", AsyncMock(return_value={"audit": claim}))
    models = AsyncMock()
    report = AsyncMock()
    monkeypatch.setattr(audit, "list_qualified_models", models)
    monkeypatch.setattr(audit, "_report", report)
    result = await audit.audit_document_build({}, "fixture-build", execution=SimpleNamespace())
    assert result.status == "page_limit" and not result.passed
    models.assert_not_awaited()
    report.assert_awaited_once()
