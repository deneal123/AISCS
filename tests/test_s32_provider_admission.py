from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from service.domain import media
from service.domain.client import active, provider_snapshot, registry
from service.domain.client.model_catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.model_requirements import (
    ModelRequirement,
    ProviderQualificationStatus,
)
from service.domain.client.provider_admission import RunProviderAdmission, RunProviderSnapshot
from service.domain.client.providers.model_list_cache import ModelListCache
from service.domain.run_context import PrivateRunResources, use_run_execution


def _catalog(provider: str, model: str) -> ProviderModelCatalog:
    return ProviderModelCatalog(
        provider=provider,
        models=(model,),
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )


def _snapshot(*records: ProviderModelRecord) -> RunProviderSnapshot:
    catalog = ProviderModelCatalog(
        provider="provider",
        models=tuple(record.model_id for record in records),
        records=records,
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )
    return RunProviderSnapshot(
        catalogs={"provider": catalog},
        records={"provider": records},
        clients={"provider": object()},
        owner_index={record.model_id: "provider" for record in records},
        provider_order=("provider",),
        active_provider="provider",
        configuration_generation="generation",
    )


@pytest.mark.asyncio
async def test_provider_metadata_is_converted_to_bounded_capability_evidence() -> None:
    cache = ModelListCache(name="Provider", provider="provider", ttl_fn=lambda: 60)

    async def fetch(_client):
        return SimpleNamespace(
            data=[
                {
                    "id": "opaque-live-model",
                    "capabilities": ["chat", "private-value"],
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        )

    catalog = await cache.get_snapshot(client=object(), fetch=fetch)

    assert catalog.records == (
        ProviderModelRecord(
            model_id="opaque-live-model",
            capabilities=frozenset({"chat", "tools", "vision"}),
            evidence_source=CapabilityEvidenceSource.PROVIDER_METADATA,
        ),
    )


def test_snapshot_is_immutable_and_unknown_capabilities_fail_closed() -> None:
    unknown = ProviderModelRecord(model_id="opaque")
    admission = RunProviderAdmission(_snapshot(unknown))

    decision = admission.qualify(
        "provider",
        requirement=ModelRequirement(),
        prefer="opaque",
        pick_model=lambda models, _prefer: models[0] if models else None,
    )

    assert decision.status is ProviderQualificationStatus.NO_COMPATIBLE_MODEL
    assert decision.model is None
    with pytest.raises(TypeError):
        admission.snapshot.catalogs["other"] = admission.snapshot.catalogs["provider"]
    with pytest.raises(FrozenInstanceError):
        admission.snapshot.active_provider = "other"


def test_qualification_is_memoized_by_provider_requirement_and_preference() -> None:
    record = ProviderModelRecord(
        model_id="chat-tools",
        capabilities=frozenset({"chat", "tools"}),
        evidence_source=CapabilityEvidenceSource.PROVIDER_METADATA,
    )
    admission = RunProviderAdmission(_snapshot(record))
    picker_calls = 0

    def picker(models: list[str], _prefer: str | None) -> str | None:
        nonlocal picker_calls
        picker_calls += 1
        return models[0] if models else None

    first = admission.qualify(
        "provider",
        requirement=ModelRequirement(tools=True),
        prefer=None,
        pick_model=picker,
    )
    second = admission.qualify(
        "provider",
        requirement=ModelRequirement(tools=True),
        prefer=None,
        pick_model=picker,
    )

    assert first is second
    assert first.model == "chat-tools"
    assert picker_calls == 1
    assert admission.cache_size == 1


@pytest.mark.asyncio
async def test_run_snapshot_survives_refresh_and_next_run_observes_new_catalog(
    monkeypatch,
) -> None:
    state = {"model": "gpt-4o-mini", "fetches": 0, "generation": "one"}
    client_one = object()
    client_two = object()
    active_client = {"value": client_one}

    async def fetch_catalogs(**_kwargs):
        state["fetches"] += 1
        return {"openai": _catalog("openai", state["model"])}

    monkeypatch.setattr(registry, "_fetch_provider_catalogs", fetch_catalogs)
    monkeypatch.setattr(active, "get_active_provider", lambda: "openai")
    monkeypatch.setattr(active, "get_openai_client", lambda: active_client["value"])
    monkeypatch.setattr(
        provider_snapshot,
        "_configuration_generation",
        lambda _catalogs, _leases=None: state["generation"],
    )

    with use_run_execution(PrivateRunResources()) as first_execution:
        first = await registry.initialize_run_provider_admission(first_execution)
        state["model"] = "gpt-4o"
        state["generation"] = "two"
        active_client["value"] = client_two
        same = await registry.initialize_run_provider_admission(first_execution)
        decision = await registry.qualify_model("openai", prefer="gpt-4o-mini")

        assert same is first
        assert decision.model == "gpt-4o-mini"
        assert first.snapshot.client_for("openai") is client_one
        assert first.snapshot.configuration_generation == "one"
        assert state["fetches"] == 1

    with use_run_execution(PrivateRunResources()) as second_execution:
        second = await registry.initialize_run_provider_admission(second_execution)
        decision = await registry.qualify_model("openai", prefer="gpt-4o")

        assert decision.model == "gpt-4o"
        assert second.snapshot.client_for("openai") is client_two
        assert second.snapshot.configuration_generation == "two"
        assert second.snapshot is not first.snapshot
        assert state["fetches"] == 2


@pytest.mark.asyncio
async def test_owner_index_and_qualified_lists_share_the_run_snapshot(monkeypatch) -> None:
    async def fetch_catalogs(**_kwargs):
        return {
            "openai": _catalog("openai", "gpt-4o"),
            "gigachat": _catalog("gigachat", "GigaChat-2"),
        }

    monkeypatch.setattr(registry, "_fetch_provider_catalogs", fetch_catalogs)
    monkeypatch.setattr(active, "get_active_provider", lambda: "gigachat")
    monkeypatch.setattr(active, "get_openai_client", object)

    with use_run_execution(PrivateRunResources()) as execution:
        admission = await registry.initialize_run_provider_admission(execution)
        chat_models = await registry.list_qualified_models()
        tool_models = await registry.list_qualified_models(ModelRequirement(tools=True))

    assert admission.snapshot.provider_order[0] == "gigachat"
    assert admission.snapshot.owner_for("GigaChat-2") == "gigachat"
    assert chat_models[:2] == ["GigaChat-2", "gpt-4o"]
    assert tool_models[:2] == ["GigaChat-2", "gpt-4o"]
    assert admission.cache_size == 4


@pytest.mark.asyncio
async def test_vision_uses_captured_owner_client_without_live_catalog(monkeypatch) -> None:
    seen: dict[str, object] = {}

    async def create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="captured vision"))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    record = ProviderModelRecord(
        model_id="gpt-4o-mini",
        capabilities=frozenset({"chat", "vision"}),
        evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
    )
    snapshot = _snapshot(record)
    admission = RunProviderAdmission(
        RunProviderSnapshot(
            catalogs=snapshot.catalogs,
            records=snapshot.records,
            clients={"provider": client},
            owner_index=snapshot.owner_index,
            provider_order=snapshot.provider_order,
            active_provider=snapshot.active_provider,
            configuration_generation=snapshot.configuration_generation,
        )
    )
    monkeypatch.setattr(media, "decode_barcodes", lambda _content: [])

    with use_run_execution(PrivateRunResources()) as execution:
        execution.provider_admission = admission
        result = await media.describe_image(
            b"synthetic-image",
            "image/png",
            "fixture.png",
            execution=execution,
        )

    assert seen["model"] == "gpt-4o-mini"
    assert "captured vision" in result
