from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.client import registry
from service.domain.client.model_catalog import (
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
)
from service.domain.client.model_requirements import (
    ModelRequirement,
    ProviderQualificationStatus,
)
from service.domain.client.providers.model_list_cache import ModelListCache
from service.domain.client.providers.spec import ProviderSpec


class _AuthFailure(RuntimeError):
    status_code = 401


def _cache(*, fallback: list[str] | None = None) -> ModelListCache:
    return ModelListCache(
        name="Provider",
        provider="provider",
        ttl_fn=lambda: 180,
        fallback=fallback,
        fetch_timeout_sec=0.1,
    )


@pytest.mark.asyncio
async def test_successful_empty_catalog_is_live_and_authoritative() -> None:
    cache = _cache(fallback=["static-chat"])

    async def fetch(_client):
        return SimpleNamespace(data=[])

    snapshot = await cache.get_snapshot(client=object(), fetch=fetch)

    assert snapshot.models == ()
    assert snapshot.source is ModelCatalogSource.LIVE
    assert snapshot.status is ModelCatalogStatus.EMPTY
    assert snapshot.fresh is True
    assert snapshot.authoritative is True


@pytest.mark.asyncio
async def test_malformed_catalog_uses_only_profiled_cold_fallback() -> None:
    cache = _cache(fallback=["static-chat"])

    async def fetch(_client):
        return {"unexpected": "shape"}

    snapshot = await cache.get_snapshot(client=object(), fetch=fetch)

    assert snapshot.models == ("static-chat",)
    assert snapshot.source is ModelCatalogSource.STATIC_FALLBACK
    assert snapshot.status is ModelCatalogStatus.MALFORMED
    assert snapshot.fresh is False


@pytest.mark.asyncio
async def test_timeout_serves_stale_authoritative_inventory() -> None:
    cache = _cache(fallback=["static-chat"])

    async def seed(_client):
        return SimpleNamespace(data=[SimpleNamespace(id="live-chat")])

    async def timeout(_client):
        raise TimeoutError

    live = await cache.get_snapshot(client=object(), fetch=seed)
    stale = await cache.get_snapshot(client=object(), fetch=timeout, force_refresh=True)

    assert live.models == ("live-chat",)
    assert stale.models == live.models
    assert stale.source is ModelCatalogSource.STALE
    assert stale.status is ModelCatalogStatus.TIMEOUT
    assert stale.fresh is False


@pytest.mark.asyncio
async def test_auth_failure_is_bounded_and_uses_cold_fallback() -> None:
    cache = _cache(fallback=["static-chat"])

    async def fetch(_client):
        raise _AuthFailure("private response body")

    snapshot = await cache.get_snapshot(client=object(), fetch=fetch)

    assert snapshot.source is ModelCatalogSource.STATIC_FALLBACK
    assert snapshot.status is ModelCatalogStatus.AUTH
    assert "private response body" not in repr(snapshot)


@pytest.mark.asyncio
async def test_configuration_identity_invalidates_cached_inventory() -> None:
    cache = _cache()
    calls = 0

    async def fetch(_client):
        nonlocal calls
        calls += 1
        return SimpleNamespace(data=[SimpleNamespace(id=f"model-{calls}")])

    first = await cache.get_snapshot(client=object(), fetch=fetch, configuration_key="one")
    cached = await cache.get_snapshot(client=object(), fetch=fetch, configuration_key="one")
    changed = await cache.get_snapshot(client=object(), fetch=fetch, configuration_key="two")

    assert first.models == cached.models == ("model-1",)
    assert changed.models == ("model-2",)
    assert calls == 2


@pytest.mark.asyncio
async def test_embedding_only_gigachat_live_catalog_never_activates_fallback() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("Embeddings-2",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    decision = await registry.qualify_model(
        "gigachat",
        prefer="GigaChat-2",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )

    assert decision.model is None
    assert decision.candidate_count == 0
    assert decision.status is ProviderQualificationStatus.NO_COMPATIBLE_MODEL
    assert decision.catalog_source is ModelCatalogSource.LIVE


@pytest.mark.asyncio
async def test_unknown_live_gigachat_model_is_not_inferred_to_support_chat() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("opaque-new-model",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    decision = await registry.qualify_model("gigachat", catalog=catalog)

    assert decision.model is None
    assert decision.status is ProviderQualificationStatus.NO_COMPATIBLE_MODEL


@pytest.mark.asyncio
async def test_declared_live_gigachat_model_is_qualified_for_tools() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("GigaChat-2",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    decision = await registry.qualify_model(
        "gigachat",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )

    assert decision.model == "GigaChat-2"
    assert decision.status is ProviderQualificationStatus.COMPATIBLE


@pytest.mark.asyncio
async def test_live_gigachat_3_lightning_is_qualified_for_tools_exactly() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("Embeddings-2", "GigaChat-3-Lightning", "GigaChat-3-Pro"),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    decision = await registry.qualify_model(
        "gigachat",
        prefer="GigaChat-3-Lightning",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )

    assert decision.model == "GigaChat-3-Lightning"
    assert decision.candidate_count == 2
    assert decision.status is ProviderQualificationStatus.COMPATIBLE


@pytest.mark.asyncio
async def test_unknown_live_gigachat_3_alias_remains_fail_closed() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("GigaChat-3-Unknown",),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )

    decision = await registry.qualify_model(
        "gigachat",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )

    assert decision.model is None
    assert decision.status is ProviderQualificationStatus.NO_COMPATIBLE_MODEL


@pytest.mark.asyncio
async def test_profiled_cold_fallback_is_explicitly_unverified() -> None:
    catalog = ProviderModelCatalog(
        provider="gigachat",
        models=("GigaChat-2", "GigaChat-2-Pro"),
        source=ModelCatalogSource.STATIC_FALLBACK,
        status=ModelCatalogStatus.TIMEOUT,
        fresh=False,
    )

    tools = await registry.qualify_model(
        "gigachat",
        requirement=ModelRequirement(tools=True),
        catalog=catalog,
    )
    vision = await registry.qualify_model(
        "gigachat",
        requirement=ModelRequirement(vision=True),
        catalog=catalog,
    )

    assert tools.model in {"GigaChat-2", "GigaChat-2-Pro"}
    assert tools.status is ProviderQualificationStatus.COMPATIBLE_UNVERIFIED
    assert vision.model is None
    assert vision.status is ProviderQualificationStatus.CATALOG_UNAVAILABLE


def test_provider_spec_requires_exact_safe_fallback_profiles() -> None:
    base = {
        "name": "provider",
        "label": "Provider",
        "default_base_url": "https://provider.invalid",
        "api_key_field": "openai_api_key",
    }
    with pytest.raises(ValueError, match="exact capability profiles"):
        ProviderSpec(**base, fallback_models=("chat",))
    with pytest.raises(ValueError, match="requires chat"):
        ProviderSpec(
            **base,
            fallback_models=("tool-only",),
            fallback_model_capabilities=(("tool-only", ("tools",)),),
        )
    with pytest.raises(ValueError, match="invalid fallback capabilities"):
        ProviderSpec(
            **base,
            fallback_models=("unknown",),
            fallback_model_capabilities=(("unknown", ("chat", "audio")),),
        )
