from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from service.domain.client.model_catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.provider_admission import RunProviderAdmission, RunProviderSnapshot
from service.domain.client.provider_generation import (
    ProviderGenerationManager,
    ProviderGenerationStatus,
)
from service.domain.client.provider_operations import (
    ProviderAdmissionStatus,
    ProviderOperation,
)
from service.domain.client.providers.gigachat import SPEC as GIGACHAT_SPEC
from service.domain.client.providers.model_list_cache import ModelListCache
from service.domain.run_context import PrivateRunResources, use_run_execution


class _Client:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


def _pick(models: list[str], _prefer: str | None) -> str | None:
    return models[0] if models else None


def _catalog(*records: ProviderModelRecord) -> ProviderModelCatalog:
    return ProviderModelCatalog(
        provider="openai",
        models=tuple(record.model_id for record in records),
        records=records,
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )


def _admission(client: object, *records: ProviderModelRecord) -> RunProviderAdmission:
    catalog = _catalog(*records)
    return RunProviderAdmission(
        RunProviderSnapshot(
            catalogs={"openai": catalog},
            records={"openai": records},
            clients={"openai": client},
            owner_index={record.model_id: "openai" for record in records},
            provider_order=("openai",),
            active_provider="openai",
            configuration_generation="safe-digest",
            generation_sequences={"openai": 7},
        )
    )


@pytest.mark.asyncio
async def test_retired_client_closes_only_after_last_lease() -> None:
    manager = ProviderGenerationManager("provider")
    old = _Client()
    new = _Client()
    manager.publish(client=old, configuration_digest="old")
    first = manager.acquire()
    second = manager.acquire()

    manager.publish(client=new, configuration_digest="new")
    await asyncio.sleep(0)
    assert old.close_count == 0
    assert manager.retired_count == 1

    first.release()
    await asyncio.sleep(0)
    assert old.close_count == 0
    second.release()
    await asyncio.sleep(0)
    assert old.close_count == 1
    second.release()
    assert old.close_count == 1


def test_client_and_catalog_publish_as_one_generation() -> None:
    manager = ProviderGenerationManager("provider")
    old_catalog = _catalog(
        ProviderModelRecord(
            model_id="old",
            capabilities=frozenset({"chat"}),
            evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
        )
    )
    new_catalog = _catalog(
        ProviderModelRecord(
            model_id="new",
            capabilities=frozenset({"chat", "tools"}),
            evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
        )
    )
    old_client = object()
    new_client = object()
    manager.publish(client=old_client, configuration_digest="old", catalog=old_catalog)
    running = manager.acquire()

    manager.publish(client=new_client, configuration_digest="new", catalog=new_catalog)
    future = manager.acquire()

    assert (running.client, running.catalog) == (old_client, old_catalog)
    assert (future.client, future.catalog) == (new_client, new_catalog)
    running.release()
    future.release()


def test_run_context_releases_provider_generation_once() -> None:
    manager = ProviderGenerationManager("provider")
    manager.publish(client=object(), configuration_digest="one")
    lease = manager.acquire()
    snapshot = RunProviderSnapshot(
        catalogs={},
        records={},
        clients={},
        owner_index={},
        provider_order=(),
        active_provider="provider",
        configuration_generation="one",
        leases=(lease,),
    )

    with use_run_execution(PrivateRunResources()) as execution:
        execution.provider_admission = RunProviderAdmission(snapshot)
        assert manager.leased_count == 1

    assert manager.leased_count == 0
    execution.close()
    assert manager.leased_count == 0


@pytest.mark.asyncio
async def test_failed_rebuild_is_unavailable_only_to_new_leases() -> None:
    manager = ProviderGenerationManager("provider")
    old = _Client()
    manager.publish(client=old, configuration_digest="old")
    running = manager.acquire()

    failed = manager.publish(client=None, configuration_digest="new")
    next_run = manager.acquire()

    assert running.client is old
    assert failed.status is ProviderGenerationStatus.UNAVAILABLE
    assert next_run.client is None
    assert old.close_count == 0

    next_run.release()
    running.release()
    await asyncio.sleep(0)
    assert old.close_count == 1


@pytest.mark.asyncio
async def test_shutdown_drain_closes_current_client_after_final_owner() -> None:
    manager = ProviderGenerationManager("provider")
    client = _Client()
    manager.publish(client=client, configuration_digest="current")

    await manager.drain()

    assert client.close_count == 1
    assert manager.current.status is ProviderGenerationStatus.RETIRED


def test_catalog_refresh_is_visible_only_to_future_generation_leases() -> None:
    manager = ProviderGenerationManager("provider")
    manager.publish(client=object(), configuration_digest="current")
    running = manager.acquire()
    catalog = _catalog(
        ProviderModelRecord(
            model_id="chat",
            capabilities=frozenset({"chat"}),
            evidence_source=CapabilityEvidenceSource.PROVIDER_METADATA,
        )
    )

    assert manager.attach_catalog(sequence=running.sequence, catalog=catalog)
    future = manager.acquire()

    assert running.catalog is None
    assert future.catalog is catalog
    running.release()
    future.release()


def test_operation_admission_distinguishes_vision_and_image_output() -> None:
    admission = _admission(
        object(),
        ProviderModelRecord(
            model_id="vision-only",
            capabilities=frozenset({"chat", "vision"}),
            evidence_source=CapabilityEvidenceSource.PROVIDER_METADATA,
        ),
        ProviderModelRecord(
            model_id="image-output",
            capabilities=frozenset({"chat", "image_output"}),
            evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
        ),
    )
    vision = admission.admit(
        "openai",
        operation=ProviderOperation.VISION_INPUT,
        prefer=None,
        pick_model=_pick,
    )
    image = admission.admit(
        "openai",
        operation=ProviderOperation.IMAGE_OUTPUT,
        prefer=None,
        pick_model=_pick,
    )

    assert vision.model == "vision-only"
    assert image.model == "image-output"
    assert image.generation_sequence == 7


def test_embedding_admission_requires_the_expected_dimension() -> None:
    admission = _admission(
        object(),
        ProviderModelRecord(
            model_id="embedding",
            capabilities=frozenset({"embeddings"}),
            evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
            embedding_dimension=1024,
        ),
    )
    accepted = admission.admit(
        "openai",
        operation=ProviderOperation.EMBEDDINGS,
        expected_embedding_dimension=1024,
        pick_model=_pick,
    )
    rejected = admission.admit(
        "openai",
        operation=ProviderOperation.EMBEDDINGS,
        expected_embedding_dimension=1536,
        pick_model=_pick,
    )

    assert accepted.status is ProviderAdmissionStatus.ADMITTED
    assert accepted.embedding_dimension == 1024
    assert rejected.status is ProviderAdmissionStatus.OPERATION_UNSUPPORTED


def test_exact_static_fallback_profile_is_admitted_but_marked_unverified() -> None:
    record = ProviderModelRecord(
        model_id="cold-model",
        capabilities=frozenset({"chat"}),
        evidence_source=CapabilityEvidenceSource.STATIC_FALLBACK,
    )
    catalog = ProviderModelCatalog(
        provider="openai",
        models=(record.model_id,),
        records=(record,),
        source=ModelCatalogSource.STATIC_FALLBACK,
        status=ModelCatalogStatus.TIMEOUT,
        fresh=False,
    )
    admission = RunProviderAdmission(
        RunProviderSnapshot(
            catalogs={"openai": catalog},
            records={"openai": (record,)},
            clients={"openai": object()},
            owner_index={record.model_id: "openai"},
            provider_order=("openai",),
            active_provider="openai",
            configuration_generation="cold",
        )
    )

    decision = admission.admit(
        "openai",
        operation=ProviderOperation.CHAT,
        pick_model=_pick,
    )

    assert decision.status is ProviderAdmissionStatus.ADMITTED_UNVERIFIED


def test_tool_admission_is_cached_with_compiled_private_payload() -> None:
    admission = _admission(
        object(),
        ProviderModelRecord(
            model_id="tool-model",
            capabilities=frozenset({"chat", "tools"}),
            evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
        ),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Read safe fixture data.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    first = admission.admit(
        "openai",
        operation=ProviderOperation.TOOL_CHAT,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        pick_model=_pick,
    )
    second = admission.admit(
        "openai",
        operation=ProviderOperation.TOOL_CHAT,
        tools=tools,
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        pick_model=_pick,
    )

    assert first is second
    assert first.compiled_tools is not None
    assert first.compiled_tools.canonical_names == ("lookup",)


@pytest.mark.asyncio
async def test_provider_metadata_accepts_only_explicit_non_chat_operations() -> None:
    cache = ModelListCache(name="Provider", provider="provider", ttl_fn=lambda: 60)

    async def fetch(_client):
        return type(
            "Response",
            (),
            {
                "data": [
                    {
                        "id": "opaque-image",
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["image"],
                        },
                    },
                    {
                        "id": "opaque-embedding",
                        "type": "embedding",
                        "embedding_dimension": 768,
                    },
                ]
            },
        )()

    snapshot = await cache.get_snapshot(client=object(), fetch=fetch)

    records = {record.model_id: record for record in snapshot.records}
    assert records["opaque-image"].capabilities == frozenset({"image_output"})
    assert records["opaque-embedding"].capabilities == frozenset({"embeddings"})
    assert records["opaque-embedding"].embedding_dimension == 768


def test_gigachat_embedding_profile_does_not_grant_chat() -> None:
    assert GIGACHAT_SPEC.capabilities_for_model("Embeddings") == frozenset({"embeddings"})
    assert GIGACHAT_SPEC.embedding_dimension_for("Embeddings") == 1024


@pytest.mark.asyncio
async def test_gateway_embedding_uses_admitted_generation_and_checks_dimension() -> None:
    seen: dict = {}

    class _Embeddings:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * 3)],
            )

    client = SimpleNamespace(embeddings=_Embeddings())
    execution = SimpleNamespace(
        provider_admission=_admission(
            client,
            ProviderModelRecord(
                model_id="embedding",
                capabilities=frozenset({"embeddings"}),
                evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
                embedding_dimension=3,
            ),
        )
    )
    from service.presentation.routers.gateway.openai_v1 import _embed

    response = await _embed(
        {"model": "openai:embedding", "input": ["fixture"], "dimensions": 3},
        execution,
    )

    assert response.data[0].embedding == [0.1] * 3
    assert seen["model"] == "embedding"
