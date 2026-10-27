from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client import circuit_breaker, registry
from service.domain.client.models.list_cache import ModelListCache
from service.domain.client.providers.management.status import cached_provider_status
from service.domain.client.providers.spec import ProviderSpec
from service.shared.agent_settings import use_settings
from service.shared.provider_policy_context import use_snapshot


@pytest.mark.asyncio
async def test_status_uses_existing_evidence_and_never_discovers_or_counts_disabled(monkeypatch):
    modules = {}
    for name in ("primary", "fallback", "disabled"):
        cache = ModelListCache(name=name, ttl_fn=lambda: 1)
        await cache.get_snapshot(
            client=object(),
            configuration_key=name,
            fetch=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="model")])),
        )
        modules[name] = SimpleNamespace(
            SPEC=ProviderSpec(name=name, label=name, api_key_field="key", default_base_url=""),
            _RUNTIME=SimpleNamespace(
                models=cache,
                catalog_configuration_generation=lambda n=name: n,
                model_catalog=AsyncMock(side_effect=AssertionError("status must not probe")),
            ),
        )
    monkeypatch.setattr(registry, "PROVIDER_MODULES", modules)
    monkeypatch.setattr(circuit_breaker, "down_providers", AsyncMock(return_value={"fallback"}))
    with (
        use_settings({"llm_provider": "primary"}),
        use_snapshot({"disabled": ["disabled"], "blocked": []}),
    ):
        status = await cached_provider_status()
    assert (status["state"], status["ready"], status["total"]) == ("degraded", 1, 2)
    assert [row["state"] for row in status["providers"]] == ["ready", "unavailable", "disabled"]
    for module in modules.values():
        module._RUNTIME.model_catalog.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_distinguishes_unobserved_rotated_and_stale_credentials(monkeypatch):
    cache = ModelListCache(name="primary", ttl_fn=lambda: 1)
    assert cache.cached_health("new") == {"state": "unknown", "checked_at": None}
    await cache.get_snapshot(
        client=object(),
        configuration_key="old",
        fetch=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id="model")])),
    )
    assert cache.cached_health("old")["state"] == "ready"
    assert cache.cached_health("new")["state"] == "unknown"
    checked = cache.cached_health("old")["checked_at"]
    monkeypatch.setattr("service.domain.client.models.list_cache.time.time", lambda: checked + 100)
    assert cache.cached_health("old")["state"] == "stale"
    cache.clear()
    assert cache.cached_health("old")["state"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "policy,down,expected",
    [
        ({"disabled": [], "blocked": []}, set(), "ready"),
        ({"disabled": ["local"], "blocked": []}, set(), "disabled"),
        ({"disabled": [], "blocked": ["local"]}, set(), "unavailable"),
        ({"disabled": [], "blocked": []}, {"local"}, "unavailable"),
    ],
)
async def test_registered_local_provider_uses_shared_policy_without_probe(
    monkeypatch, policy, down, expected
):
    from service.domain.client.providers import local

    cache = ModelListCache(name="local", ttl_fn=lambda: 180)
    await cache.get_snapshot(
        client=object(),
        configuration_key="local-generation",
        fetch=AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(id=local.MODEL_ID)])),
    )
    discover = AsyncMock(side_effect=AssertionError("Статус не запускает discovery"))
    monkeypatch.setattr(
        local,
        "_RUNTIME",
        SimpleNamespace(
            models=cache,
            catalog_configuration_generation=lambda: "local-generation",
            model_catalog=discover,
        ),
    )
    monkeypatch.setattr(circuit_breaker, "down_providers", AsyncMock(return_value=down))
    with use_snapshot(policy):
        result = await cached_provider_status()
    row = next(row for row in result["providers"] if row["id"] == "local")
    assert row["label"] == "Локальная модель"
    assert row["state"] == expected
    assert row["checked_at"] > 0
    discover.assert_not_awaited()
