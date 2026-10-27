"""Construction of the immutable provider evidence captured by one agents run."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from service.domain.client.models.catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.providers.management.admission import (
    RunProviderAdmission,
    RunProviderSnapshot,
)
from service.domain.client.providers.management.generation import ProviderGenerationLease


def _configuration_generation(
    catalogs: dict[str, ProviderModelCatalog],
    leases: dict[str, ProviderGenerationLease] | None = None,
) -> str:
    from service.domain.client.registry import get_provider_module

    material: list[str] = []
    for name in sorted(catalogs):
        module = get_provider_module(name)
        runtime = getattr(module, "_RUNTIME", None) if module is not None else None
        lease = (leases or {}).get(name)
        generation = (
            lease.configuration_digest
            if lease is not None
            else runtime.catalog_configuration_generation()
            if runtime is not None and hasattr(runtime, "catalog_configuration_generation")
            else name
        )
        material.append(f"{name}:{generation}")
    return sha256("\n".join(material).encode("utf-8")).hexdigest()


def _trusted_record(model: str, trusted_catalog: dict[str, dict]) -> ProviderModelRecord | None:
    from service.domain.client.registry import is_chat_capable
    from service.shared.model_catalog import resolve_model_meta

    metadata = resolve_model_meta(model, trusted_catalog)
    if not metadata:
        return None
    capabilities = {
        value
        for value in (metadata.get("capabilities") or ())
        if value in {"tools", "vision", "image_output", "embeddings", "transcription"}
    }
    if is_chat_capable(model):
        capabilities.add("chat")
    return ProviderModelRecord(
        model_id=model,
        capabilities=frozenset(capabilities),
        evidence_source=CapabilityEvidenceSource.TRUSTED_CATALOG,
    )


def _evidence_records(
    provider: str,
    catalog: ProviderModelCatalog,
    trusted_catalog: dict[str, dict],
) -> tuple[ProviderModelRecord, ...]:
    from service.domain.client.registry import get_spec

    spec = get_spec(provider)
    existing = {record.model_id: record for record in catalog.model_records()}
    output: list[ProviderModelRecord] = []
    for model in catalog.models:
        declared = spec.capabilities_for_model(model) if spec is not None else frozenset()
        if declared:
            output.append(
                ProviderModelRecord(
                    model_id=model,
                    capabilities=declared,
                    evidence_source=(
                        CapabilityEvidenceSource.STATIC_FALLBACK
                        if catalog.source is ModelCatalogSource.STATIC_FALLBACK
                        else CapabilityEvidenceSource.LOCAL_PROFILE
                    ),
                    embedding_dimension=(
                        spec.embedding_dimension_for(model) if spec is not None else None
                    ),
                )
            )
            continue
        current = existing[model]
        if current.capabilities:
            output.append(current)
            continue
        output.append(_trusted_record(model, trusted_catalog) or current)
    return tuple(output)


def _assemble_run_admission(
    catalogs: dict[str, ProviderModelCatalog],
    trusted: dict[str, dict],
    leases: dict[str, ProviderGenerationLease],
) -> RunProviderAdmission:
    from service.domain.client import active
    from service.domain.client.registry import build_provider_order, get_provider_module

    active_name = str(active.get_active_provider()).strip().lower()
    ordered = tuple(name for name in build_provider_order(active_name) if name in catalogs)
    inventory = (*ordered, *(name for name in catalogs if name not in ordered))
    records = {name: _evidence_records(name, catalogs[name], trusted) for name in inventory}
    frozen_catalogs = {name: replace(catalogs[name], records=records[name]) for name in inventory}
    owners: dict[str, str] = {}
    for name in inventory:
        for record in records[name]:
            owners.setdefault(record.model_id, name)
    clients = {}
    for name in inventory:
        lease = leases.get(name)
        clients[name] = (
            lease.client
            if lease is not None
            else active.get_openai_client()
            if name == active_name
            else getattr(get_provider_module(name), "OPENAI_CLIENT", None)
        )
    selected_leases = tuple(leases[name] for name in inventory if name in leases)
    for name, lease in leases.items():
        if name not in inventory:
            lease.release()
    return RunProviderAdmission(
        RunProviderSnapshot(
            catalogs=frozen_catalogs,
            records=records,
            clients=clients,
            owner_index=owners,
            provider_order=ordered,
            active_provider=active_name,
            configuration_generation=_configuration_generation(frozen_catalogs, leases),
            generation_sequences={
                name: leases[name].sequence for name in inventory if name in leases
            },
            leases=selected_leases,
        )
    )


async def build_run_provider_admission() -> RunProviderAdmission:
    from service.domain.client.registry import PROVIDER_MODULES, _fetch_provider_catalogs
    from service.shared.model_catalog import cached_openrouter_catalog

    leases: dict[str, ProviderGenerationLease] = {}
    for name, module in PROVIDER_MODULES.items():
        runtime = getattr(module, "_RUNTIME", None)
        if runtime is None or not hasattr(runtime, "acquire_generation"):
            continue
        lease = runtime.acquire_generation()
        if lease.client is None:
            lease.release()
            continue
        leases[name] = lease
    try:
        generation_catalogs = {
            name: lease.catalog for name, lease in leases.items() if lease.catalog is not None
        }
        catalogs = await _fetch_provider_catalogs(
            clients={
                name: (
                    leases[name].client
                    if name in leases
                    else getattr(module, "OPENAI_CLIENT", None)
                )
                for name, module in PROVIDER_MODULES.items()
            },
            configuration_keys={name: lease.configuration_digest for name, lease in leases.items()},
            generation_catalogs=generation_catalogs,
            cached_only=True,
        )
    except Exception:  # noqa: BLE001 - an empty bounded snapshot is safer than leaking details
        catalogs = {}
    needs_trusted_evidence = any(
        not record.capabilities
        for catalog in catalogs.values()
        for record in catalog.model_records()
    )
    if needs_trusted_evidence:
        try:
            trusted = cached_openrouter_catalog()
        except Exception:  # noqa: BLE001 - unknown remains fail-closed
            trusted = {}
    else:
        trusted = {}
    for name, catalog in catalogs.items():
        lease = leases.get(name)
        module = PROVIDER_MODULES.get(name)
        runtime = getattr(module, "_RUNTIME", None) if module is not None else None
        if lease is not None and runtime is not None:
            runtime.attach_generation_catalog(lease.sequence, catalog)
    try:
        return _assemble_run_admission(catalogs, trusted, leases)
    except BaseException:
        for lease in leases.values():
            lease.release()
        raise


__all__ = ["build_run_provider_admission"]
