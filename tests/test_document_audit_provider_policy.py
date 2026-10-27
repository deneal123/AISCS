"""Deferred document audit must use its own backend policy, not the last chat's."""

import asyncio
from types import SimpleNamespace

import pytest

from service.presentation.routers.capabilities import document_audit as endpoint
from service.shared import provider_policy_context as policy


@pytest.mark.asyncio
async def test_audit_policy_is_scoped_and_restored(monkeypatch):
    monkeypatch.setattr(endpoint, "internal_auth", lambda _: None)
    monkeypatch.setattr(policy, "_LAST_SEEN", None)
    observed = []

    async def audit(_ref, _build, *, execution):
        observed.append((policy.get_disabled(), policy.get_blocked()))
        await asyncio.sleep(0)
        assert execution.usage.project_since(0)["total"] == 0
        return SimpleNamespace(status="passed", passed=True, retryable=False, diagnostics=())

    monkeypatch.setattr(endpoint, "audit_document_build", audit)
    with policy.use_snapshot({"disabled": ["gigachat"], "blocked": []}):
        payload = endpoint.DocumentAuditRequest(
            build_id="test-build",
            workspace_ref={},
            provider_policy={"disabled": ["openai"], "blocked": ["openrouter"]},
        )
        result = await endpoint.audit_document(payload, authorization="private")
        assert policy.get_disabled() == frozenset({"gigachat"})
    assert observed == [(frozenset({"openai"}), frozenset({"openrouter"}))]
    assert result["passed"] is True
    assert policy.get_disabled() is None


@pytest.mark.asyncio
async def test_concurrent_audits_do_not_share_provider_policy(monkeypatch):
    monkeypatch.setattr(endpoint, "internal_auth", lambda _: None)
    monkeypatch.setattr(policy, "_LAST_SEEN", None)
    observed = {}

    async def audit(_ref, build, *, execution):
        await asyncio.sleep(0)
        observed[build] = policy.get_disabled()
        return SimpleNamespace(
            status="vision_unavailable", passed=False, retryable=True, diagnostics=()
        )

    monkeypatch.setattr(endpoint, "audit_document_build", audit)
    await asyncio.gather(
        *(
            endpoint.audit_document(
                endpoint.DocumentAuditRequest(
                    build_id=build,
                    workspace_ref={},
                    provider_policy={"disabled": [disabled], "blocked": []},
                ),
                authorization="private",
            )
            for build, disabled in (("build-one", "openai"), ("build-two", "gigachat"))
        )
    )
    assert observed == {"build-one": frozenset({"openai"}), "build-two": frozenset({"gigachat"})}
    assert policy.get_disabled() is None
