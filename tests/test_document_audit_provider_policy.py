"""Backend policy is mandatory for new deferred visual-audit requests."""

from unittest.mock import AsyncMock

import pytest

from service.infrastructure import provider_policy_store as policy
from service.infrastructure.agents_client.document_audit import client as document_audit


@pytest.mark.asyncio
async def test_audit_carries_current_policy_even_when_empty(monkeypatch):
    monkeypatch.setattr(policy, "disabled_providers", lambda: frozenset())
    monkeypatch.setattr(policy, "blocked_providers", AsyncMock(return_value=frozenset()))
    request = AsyncMock(return_value={"status": "vision_unavailable", "passed": False})
    monkeypatch.setattr(document_audit.SidecarClient, "request_json", request)
    await document_audit.audit_document(object(), workspace_ref={}, build_id="test-build")
    assert request.call_args.kwargs["json_body"]["provider_policy"] == {
        "disabled": [],
        "blocked": [],
    }


@pytest.mark.asyncio
async def test_audit_carries_disabled_and_blocked_providers(monkeypatch):
    monkeypatch.setattr(policy, "disabled_providers", lambda: frozenset({"openai"}))
    monkeypatch.setattr(
        policy, "blocked_providers", AsyncMock(return_value=frozenset({"openrouter"}))
    )
    request = AsyncMock(return_value={"status": "passed", "passed": True})
    monkeypatch.setattr(document_audit.SidecarClient, "request_json", request)
    await document_audit.audit_document(object(), workspace_ref={}, build_id="test-build")
    assert request.call_args.kwargs["json_body"]["provider_policy"] == {
        "disabled": ["openai"],
        "blocked": ["openrouter"],
    }


@pytest.mark.asyncio
async def test_unavailable_policy_never_starts_unrestricted_audit(monkeypatch, caplog):
    marker = "private-provider-policy-exception-marker"
    monkeypatch.setattr(policy, "disabled_providers", lambda: frozenset())
    monkeypatch.setattr(policy, "blocked_providers", AsyncMock(side_effect=RuntimeError(marker)))
    request = AsyncMock()
    monkeypatch.setattr(document_audit.SidecarClient, "request_json", request)
    result = await document_audit.audit_document(object(), workspace_ref={}, build_id="test-build")
    assert result == {"status": "unavailable", "passed": False, "retryable": True}
    request.assert_not_awaited()
    assert marker not in caplog.text
