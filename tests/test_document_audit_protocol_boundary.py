"""Audit success requires typed flags, never the truthiness of provider data."""

from unittest.mock import AsyncMock

import pytest

from service.infrastructure.agents_client.document_audit import client as document_audit


@pytest.mark.asyncio
@pytest.mark.parametrize("passed", ["false", "true", 1, [True], {"passed": True}])
async def test_non_boolean_passed_is_retriable_protocol_failure(monkeypatch, passed):
    usage = {"calls": [{"model": "GigaChat-2", "prompt": 12, "completion": 3}]}
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        document_audit.SidecarClient,
        "request_json",
        AsyncMock(
            return_value={
                "status": "passed",
                "passed": passed,
                "retryable": False,
                "usage": usage,
            }
        ),
    )
    result = await document_audit.audit_document(
        object(), workspace_ref={}, build_id="fixture-build"
    )
    assert result["passed"] is False
    assert result["retryable"] is True
    assert result["status"] == "protocol"
    assert result["usage"]["total"] == 15


@pytest.mark.asyncio
async def test_failure_status_cannot_claim_passed_and_unknown_status_is_not_exposed(monkeypatch):
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    request = AsyncMock(
        return_value={
            "status": "PRIVATE_PROVIDER_RESPONSE",
            "passed": True,
            "retryable": False,
        }
    )
    monkeypatch.setattr(document_audit.SidecarClient, "request_json", request)
    result = await document_audit.audit_document(
        object(), workspace_ref={}, build_id="fixture-build"
    )
    assert result == {"status": "protocol", "passed": False, "retryable": True, "usage": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("retryable", ["false", 0, None, []])
async def test_retryability_requires_a_boolean(monkeypatch, retryable):
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        document_audit.SidecarClient,
        "request_json",
        AsyncMock(
            return_value={
                "status": "failed",
                "passed": False,
                "retryable": retryable,
            }
        ),
    )
    result = await document_audit.audit_document(
        object(), workspace_ref={}, build_id="fixture-build"
    )
    assert result == {"status": "protocol", "passed": False, "retryable": True, "usage": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,passed", [("failed", True), ("passed", False)])
async def test_inconsistent_status_is_not_a_valid_verdict(monkeypatch, status, passed):
    monkeypatch.setattr(document_audit.provider_policy, "disabled_providers", lambda: ())
    monkeypatch.setattr(
        document_audit.provider_policy, "blocked_providers", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        document_audit.SidecarClient,
        "request_json",
        AsyncMock(
            return_value={
                "status": status,
                "passed": passed,
                "retryable": False,
            }
        ),
    )
    result = await document_audit.audit_document(
        object(), workspace_ref={}, build_id="fixture-build"
    )
    assert result == {"status": "protocol", "passed": False, "retryable": True, "usage": {}}
