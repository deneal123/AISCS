"""Локальная модель использует общий provider runtime и точные capabilities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client import registry
from service.domain.client.protocol.compiler import compile_toolset
from service.domain.client.providers import local
from service.shared.model_catalog import resolve_context_window_ex


def test_local_provider_is_registered_without_foreign_capabilities():
    assert registry.get_provider_module("local") is local
    assert local.SPEC.supports_stream_usage
    assert local.SPEC.require_declared_model_capabilities
    assert local.SPEC.fallback_model_capabilities == ((local.MODEL_ID, ("chat", "tools")),)
    assert resolve_context_window_ex(local.MODEL_ID, {}) == (8192, True)
    assert not local.SPEC.embedding_dimensions


@pytest.mark.asyncio
async def test_local_chat_keeps_tool_payload_usage_and_explicit_client():
    receipt = object()
    create = AsyncMock(return_value=receipt)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    tools = [{"type": "function", "function": {"name": "read_file"}}]
    result = await local.create_chat_completion(
        [{"role": "user", "content": "Прочитай файл"}],
        local.MODEL_ID,
        client=client,
        tools=tools,
        tool_choice="auto",
        max_tokens=128,
    )
    assert result is receipt
    assert create.await_args.kwargs["tools"] == tools
    assert create.await_args.kwargs["tool_choice"] == "auto"
    assert create.await_args.kwargs["model"] == local.MODEL_ID


def test_unconfigured_local_provider_does_not_borrow_foreign_key(monkeypatch):
    from service.domain.client.providers import credentials
    from service.settings import config

    monkeypatch.setattr(config.agents, "local_api_key", "")
    monkeypatch.setattr(config.agents, "openai_api_key", "synthetic-foreign-key")
    monkeypatch.setattr(credentials, "_overrides", {})
    assert local._RUNTIME.resolve_api_key() == ""
    assert local._RUNTIME.create_client() is None


@pytest.mark.parametrize(
    "choice",
    [
        "required",
        {"type": "function", "function": {"name": "read_file"}},
    ],
)
def test_verified_structured_tool_choice_is_not_weakened(choice):
    compiled = compile_toolset(
        [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Прочитать файл",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ],
        provider="local",
        capabilities=local.SPEC.tool_capabilities,
        tool_choice=choice,
    )
    assert compiled.choice == choice
    assert compiled.max_calls_per_round == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("local_enabled", [True, False])
async def test_cloud_inventory_cannot_claim_reserved_free_id(monkeypatch, local_enabled):
    from service.domain.client.providers.management.inventory import build_model_catalog

    inventories = {"routerai": [local.MODEL_ID, "cloud-model"]}
    if local_enabled:
        inventories["local"] = [local.MODEL_ID]
    monkeypatch.setattr(registry, "_fetch_grouped_models", AsyncMock(return_value=inventories))
    models, owners = await build_model_catalog("routerai")
    if local_enabled:
        assert owners[local.MODEL_ID] == "local"
    else:
        assert local.MODEL_ID not in models and local.MODEL_ID not in owners


@pytest.mark.asyncio
async def test_cloud_qualification_cannot_admit_reserved_free_id():
    from service.domain.client.models.catalog import (
        ModelCatalogSource,
        ModelCatalogStatus,
        ProviderModelCatalog,
    )
    from service.domain.client.models.qualification import qualify_catalog
    from service.domain.client.models.requirements import ModelRequirement
    from service.domain.client.providers import routerai

    result = await qualify_catalog(
        provider="routerai",
        spec=routerai.SPEC,
        catalog=ProviderModelCatalog(
            provider="routerai",
            models=(local.MODEL_ID,),
            source=ModelCatalogSource.LIVE,
            status=ModelCatalogStatus.AVAILABLE,
            fresh=True,
        ),
        requirement=ModelRequirement(),
        prefer=local.MODEL_ID,
        is_chat_capable=registry.is_chat_capable,
        pick_model=registry._pick_chat_capable_model,
    )
    assert result.model is None and result.candidate_count == 0


def test_frozen_admission_never_routes_free_alias_to_a_cloud_namesake():
    from service.domain.client.models.catalog import (
        ModelCatalogSource,
        ModelCatalogStatus,
        ProviderModelCatalog,
        ProviderModelRecord,
    )
    from service.domain.client.models.requirements import ModelRequirement
    from service.domain.client.providers.management.admission import (
        RunProviderAdmission,
        RunProviderSnapshot,
    )

    cloud_records = tuple(
        ProviderModelRecord(model_id=model, capabilities=frozenset({"chat"}))
        for model in ("cloud-model", local.MODEL_ID)
    )
    local_records = (
        ProviderModelRecord(model_id=local.MODEL_ID, capabilities=frozenset({"chat"})),
    )
    records = {"routerai": cloud_records, "local": local_records}
    catalogs = {
        provider: ProviderModelCatalog(
            provider=provider,
            models=tuple(row.model_id for row in rows),
            records=rows,
            source=ModelCatalogSource.LIVE,
            status=ModelCatalogStatus.AVAILABLE,
            fresh=True,
        )
        for provider, rows in records.items()
    }
    admission = RunProviderAdmission(
        RunProviderSnapshot(
            catalogs=catalogs,
            records=records,
            clients={"routerai": object(), "local": object()},
            owner_index={},
            provider_order=("routerai", "local"),
            active_provider="routerai",
            configuration_generation="g1",
        )
    )
    requirement = ModelRequirement()
    assert (
        admission.qualify(
            "routerai",
            requirement=requirement,
            prefer=local.MODEL_ID,
            pick_model=registry._pick_chat_capable_model,
        ).model
        is None
    )
    models, owners = admission.qualified_catalog(
        requirement, pick_model=registry._pick_chat_capable_model
    )
    assert local.MODEL_ID in models and owners[local.MODEL_ID] == "local"
