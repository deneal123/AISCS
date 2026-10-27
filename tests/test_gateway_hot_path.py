from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client import active, circuit_breaker, registry
from service.domain.client.models.catalog import ModelCatalogSource, ModelCatalogStatus
from service.domain.client.models.list_cache import ModelListCache
from service.domain.client.providers.management.generation import ProviderGenerationManager
from service.domain.client.providers.management.snapshot import build_run_provider_admission
from service.domain.client.providers.spec import ProviderSpec
from service.shared.agent_settings import use_settings
from service.shared.provider_policy_context import use_snapshot


def provider(name):
    spec = ProviderSpec(
        default_base_url="https://synthetic.invalid/v1",
        api_key_field="openai_api_key",
        name=name,
        label=name,
        fallback_models=(f"{name}-text",),
        fallback_model_capabilities=((f"{name}-text", ("chat", "tools")),),
    )
    cache = ModelListCache(
        name=name,
        ttl_fn=lambda: 1,
        provider=name,
        fallback=list(spec.fallback_models),
        capability_profiles=spec.fallback_model_capabilities,
    )
    manager = ProviderGenerationManager(name)
    client = object()
    manager.publish(client=client, configuration_digest=name)
    runtime = SimpleNamespace(
        acquire_generation=manager.acquire,
        cached_model_catalog=cache.cached_snapshot,
        attach_generation_catalog=lambda seq, cat: manager.attach_catalog(
            sequence=seq, catalog=cat
        ),
        catalog_configuration_generation=lambda: name,
        model_catalog=AsyncMock(side_effect=AssertionError("discovery on traffic path")),
    )
    return SimpleNamespace(SPEC=spec, OPENAI_CLIENT=client, _RUNTIME=runtime), cache


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failover,expected", [(True, ("primary", "fallback")), (False, ("primary",))]
)
async def test_cold_admission_never_discovers_and_obeys_exact_fallback_policy(
    monkeypatch, failover, expected
):
    modules = {name: provider(name)[0] for name in ("primary", "fallback", "disabled", "other")}
    monkeypatch.setattr(registry, "PROVIDER_MODULES", modules)
    monkeypatch.setattr(circuit_breaker, "down_providers", AsyncMock(return_value=set()))
    with (
        use_settings(
            {
                "llm_provider": "primary",
                "provider_fallback_order": "disabled,fallback",
                "provider_failover_enabled": failover,
            }
        ),
        use_snapshot({"disabled": ["disabled"], "blocked": []}),
    ):
        admission = await build_run_provider_admission()
        try:
            assert active.get_active_provider() == "primary"
            assert admission.snapshot.provider_order == expected
            assert "disabled" not in admission.snapshot.catalogs
            # An enabled model owner remains explicitly selectable without becoming a fallback.
            assert admission.snapshot.owner_for("other-text") == "other"
            for module in modules.values():
                module._RUNTIME.model_catalog.assert_not_awaited()
        finally:
            admission.snapshot.release()


@pytest.mark.asyncio
async def test_cached_inventory_preserves_empty_stale_and_configuration_identity(monkeypatch):
    _, cache = provider("primary")
    now = [10.0]
    monkeypatch.setattr("service.domain.client.models.list_cache.time.monotonic", lambda: now[0])
    fetch = AsyncMock(return_value=SimpleNamespace(data=[]))
    await cache.get_snapshot(client=object(), fetch=fetch, configuration_key="old")
    now[0] = 100.0
    stale = cache.cached_snapshot("old")
    assert stale.source is ModelCatalogSource.STALE
    assert stale.status is ModelCatalogStatus.EMPTY
    assert stale.models == ()
    assert stale.fresh is False
    assert cache.cached_snapshot("new").source is ModelCatalogSource.STATIC_FALLBACK
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_does_not_repeat_a_call_that_spent_its_budget(monkeypatch):
    from service.domain.client.calls import retry

    now = [0.0]
    monkeypatch.setattr(retry.time, "monotonic", lambda: now[0])

    async def failed():
        now[0] = 30.0
        raise TimeoutError

    call = AsyncMock(side_effect=failed)
    with pytest.raises(TimeoutError):
        await retry.with_retry(call, attempts=10, budget_sec=5.0)
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("warm", [False, True])
async def test_last_failed_observation_blocks_traffic_until_background_recovery(warm):
    _, cache = provider("primary")
    response = SimpleNamespace(data=[SimpleNamespace(id="primary-text")])
    if warm:
        await cache.get_snapshot(client=object(), fetch=AsyncMock(return_value=response))
    failed = await cache.get_snapshot(
        client=object(), fetch=AsyncMock(side_effect=TimeoutError), force_refresh=True
    )
    # Diagnostics retain known inventory; traffic must not resurrect it on failure.
    assert failed.models == ("primary-text",)
    assert cache.cached_snapshot().models == ()
    assert cache.cached_snapshot().status is ModelCatalogStatus.TIMEOUT
    await cache.get_snapshot(
        client=object(), fetch=AsyncMock(return_value=response), force_refresh=True
    )
    assert cache.cached_snapshot().models == ("primary-text",)
    assert cache.cached_snapshot().status is ModelCatalogStatus.AVAILABLE


@pytest.mark.asyncio
async def test_all_cooled_providers_are_not_resurrected_on_traffic(monkeypatch):
    from service.domain.client.calls import chat, streaming
    from service.domain.client.protocol import ProviderProtocolError, ProviderRoundState
    from service.domain.execution import context as run_context
    from service.domain.pipeline.errors import categorize

    modules = {name: provider(name)[0] for name in ("primary", "fallback")}
    monkeypatch.setattr(registry, "PROVIDER_MODULES", modules)
    monkeypatch.setattr(circuit_breaker, "down_providers", AsyncMock(return_value=set(modules)))
    with use_settings({"llm_provider": "primary", "provider_fallback_order": "fallback"}):
        admission = await build_run_provider_admission()
        try:
            assert admission.snapshot.provider_order == ()
            assert not admission.snapshot.catalogs
            monkeypatch.setattr(
                run_context,
                "current_execution",
                lambda: SimpleNamespace(provider_admission=admission),
            )
            with pytest.raises(ProviderProtocolError) as caught:
                await chat.create_chat_completion(messages=[], model="primary-text")
            assert categorize(caught.value).category == "provider"
            with pytest.raises(ProviderProtocolError) as caught_stream:
                async for _ in streaming.stream_provider_completion(
                    [], "primary-text", round_state=ProviderRoundState()
                ):
                    pytest.fail("unavailable pool must not emit content")
            assert categorize(caught_stream.value).category == "provider"
        finally:
            admission.snapshot.release()
    for module in modules.values():
        module._RUNTIME.model_catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_background_refresh_waits_for_policy_and_forces_fresh_observations(monkeypatch):
    from service.domain.client.models import maintenance as catalog_maintenance

    refresh = AsyncMock(return_value={})
    monkeypatch.setattr(registry, "_fetch_provider_catalogs", refresh)
    monkeypatch.setattr(catalog_maintenance, "describe", lambda: {"known": False})
    with use_settings({"provider_enabled": {}}):
        await catalog_maintenance.refresh_catalogs()
    refresh.assert_not_awaited()
    with use_settings({"provider_enabled": {"primary": True}}):
        await catalog_maintenance.refresh_catalogs()
    refresh.assert_awaited_once_with(force_refresh=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("force", [False, True])
async def test_automatic_health_is_non_billable_but_explicit_probe_is_preserved(monkeypatch, force):
    from service.domain.client import health_probe

    module, cache = provider("primary")
    catalog = await cache.get_snapshot(
        client=object(),
        fetch=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="primary-text")])),
    )
    monkeypatch.setattr(registry, "PROVIDER_MODULES", {"primary": module})
    monkeypatch.setattr(registry, "get_provider_model_catalog", AsyncMock(return_value=catalog))
    reach = AsyncMock()
    monkeypatch.setattr(health_probe, "_reach", reach)
    monkeypatch.setattr(
        health_probe,
        "_qualification_summary",
        AsyncMock(return_value=(SimpleNamespace(model="primary-text"), {})),
    )
    name, result = await health_probe.probe_provider(
        "primary",
        health_probe.ProviderProbeContext(known_down=frozenset(), force_probe=force, timeout_sec=1),
    )
    assert name == "primary"
    assert result["reachable"] is True
    assert result["probe_kind"] == ("chat" if force else "catalog")
    assert reach.await_count == int(force)


@pytest.mark.asyncio
async def test_knowledge_capability_gate_reuses_admission_without_public_discovery(monkeypatch):
    from service.application.processing.processor import AgentProcessor
    from service.domain.execution import context as run_context
    from service.shared import model_catalog

    monkeypatch.setattr(registry, "PROVIDER_MODULES", {"primary": provider("primary")[0]})
    monkeypatch.setattr(circuit_breaker, "down_providers", AsyncMock(return_value=set()))
    discovery = AsyncMock(side_effect=AssertionError("public discovery on traffic path"))
    monkeypatch.setattr(model_catalog, "model_supports_tools", discovery)
    processor = AgentProcessor({"model": "primary-text"})
    with use_settings({"llm_provider": "primary", "provider_fallback_order": ""}):
        admission = await build_run_provider_admission()
        monkeypatch.setattr(
            run_context, "current_execution", lambda: SimpleNamespace(provider_admission=admission)
        )
        try:
            assert await processor._auto_knowledge("synthetic-user", "question") == ""
            discovery.assert_not_awaited()
        finally:
            admission.snapshot.release()
