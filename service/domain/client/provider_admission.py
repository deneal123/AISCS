"""Immutable provider evidence and run-local qualification memoization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .model_catalog import ModelCatalogSource, ProviderModelCatalog, ProviderModelRecord
from .model_requirements import (
    ModelQualification,
    ModelRequirement,
    ProviderQualificationStatus,
)
from .provider_generation import ProviderGenerationLease
from .provider_operations import (
    ProviderAdmissionStatus,
    ProviderCallAdmission,
    ProviderOperation,
    admitted_status,
    compilation_status,
    compile_admitted_toolset,
    toolset_digest,
)

ModelPicker = Callable[[list[str], str | None], str | None]


def _freeze_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True, slots=True)
class RunProviderSnapshot:
    """One immutable provider/model view shared by every stage of a run."""

    catalogs: Mapping[str, ProviderModelCatalog]
    records: Mapping[str, tuple[ProviderModelRecord, ...]]
    clients: Mapping[str, Any]
    owner_index: Mapping[str, str]
    provider_order: tuple[str, ...]
    active_provider: str
    configuration_generation: str
    generation_sequences: Mapping[str, int] = field(default_factory=dict)
    leases: tuple[ProviderGenerationLease, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalogs", _freeze_mapping(self.catalogs))
        object.__setattr__(self, "records", _freeze_mapping(self.records))
        object.__setattr__(self, "clients", _freeze_mapping(self.clients))
        object.__setattr__(self, "owner_index", _freeze_mapping(self.owner_index))
        object.__setattr__(self, "generation_sequences", _freeze_mapping(self.generation_sequences))

    def client_for(self, provider: str) -> Any | None:
        return self.clients.get(str(provider).strip().lower())

    def owner_for(self, model: str | None) -> str | None:
        return self.owner_index.get(str(model)) if model else None

    def generation_for(self, provider: str) -> int | None:
        return self.generation_sequences.get(str(provider).strip().lower())

    def release(self) -> None:
        for lease in self.leases:
            lease.release()


@dataclass(slots=True)
class RunProviderAdmission:
    """Qualification facade whose mutable memo never escapes the owning run."""

    snapshot: RunProviderSnapshot
    _evidence_cache: dict[tuple[str, ModelRequirement], tuple[str, ...]] = field(
        default_factory=dict
    )
    _decision_cache: dict[tuple[str, ModelRequirement, str | None], ModelQualification] = field(
        default_factory=dict
    )
    _call_cache: dict[tuple[Any, ...], ProviderCallAdmission] = field(default_factory=dict)

    @property
    def cache_size(self) -> int:
        return len(self._evidence_cache)

    def qualify(
        self,
        provider: str,
        *,
        requirement: ModelRequirement,
        prefer: str | None,
        pick_model: ModelPicker,
    ) -> ModelQualification:
        normalized = str(provider).strip().lower()
        decision_key = (normalized, requirement, prefer)
        if cached := self._decision_cache.get(decision_key):
            return cached

        evidence_key = (normalized, requirement)
        catalog = self.snapshot.catalogs.get(normalized)
        candidates = self._evidence_cache.get(evidence_key)
        if candidates is None:
            candidates = tuple(
                record.model_id
                for record in self.snapshot.records.get(normalized, ())
                if _record_satisfies(record, requirement)
            )
            self._evidence_cache[evidence_key] = candidates
        selected = (
            prefer if prefer and prefer in candidates else pick_model(list(candidates), prefer)
        )
        if selected is not None:
            status = (
                ProviderQualificationStatus.COMPATIBLE_UNVERIFIED
                if catalog is not None and catalog.source is ModelCatalogSource.STATIC_FALLBACK
                else ProviderQualificationStatus.COMPATIBLE
            )
        elif catalog is None or not catalog.discovery_available:
            status = ProviderQualificationStatus.CATALOG_UNAVAILABLE
        else:
            status = ProviderQualificationStatus.NO_COMPATIBLE_MODEL
        decision = ModelQualification(
            provider=normalized,
            requirement=requirement,
            status=status,
            catalog_source=(
                catalog.source if catalog is not None else ModelCatalogSource.STATIC_FALLBACK
            ),
            catalog_status=(
                catalog.status if catalog is not None else _unavailable_catalog_status()
            ),
            candidate_count=len(candidates),
            model=selected,
        )
        self._decision_cache[decision_key] = decision
        return decision

    def qualified_catalog(
        self,
        requirement: ModelRequirement,
        *,
        pick_model: ModelPicker,
    ) -> tuple[list[str], dict[str, str]]:
        models: list[str] = []
        owners: dict[str, str] = {}
        seen: set[str] = set()
        for provider in self.snapshot.provider_order:
            decision = self.qualify(
                provider,
                requirement=requirement,
                prefer=None,
                pick_model=pick_model,
            )
            if not decision.compatible:
                continue
            for record in self.snapshot.records.get(provider, ()):
                if not _record_satisfies(record, requirement):
                    continue
                owners.setdefault(record.model_id, provider)
                if record.model_id not in seen:
                    seen.add(record.model_id)
                    models.append(record.model_id)
        return models, owners

    def admit(
        self,
        provider: str,
        *,
        operation: ProviderOperation,
        prefer: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        expected_embedding_dimension: int | None = None,
        pick_model: ModelPicker,
    ) -> ProviderCallAdmission:
        """Bind model, client generation and protocol compilation in one melt-free result."""

        normalized = str(provider).strip().lower()
        digest = toolset_digest(tools, tool_choice)
        key = (
            normalized,
            operation,
            prefer,
            expected_embedding_dimension,
            digest,
        )
        cached = self._call_cache.get(key)
        if cached is not None:
            return cached

        catalog = self.snapshot.catalogs.get(normalized)
        records = tuple(
            record
            for record in self.snapshot.records.get(normalized, ())
            if operation.required_capabilities <= record.capabilities
            and (
                expected_embedding_dimension is None
                or record.embedding_dimension == expected_embedding_dimension
            )
        )
        candidate_ids = [record.model_id for record in records]
        model = prefer if prefer in candidate_ids else pick_model(candidate_ids, prefer)
        if catalog is None:
            status = ProviderAdmissionStatus.CATALOG_UNAVAILABLE
        elif (
            catalog.source is not ModelCatalogSource.STATIC_FALLBACK
            and not catalog.discovery_available
        ):
            status = ProviderAdmissionStatus.CATALOG_UNAVAILABLE
        elif not candidate_ids:
            status = ProviderAdmissionStatus.OPERATION_UNSUPPORTED
        elif model is None:
            status = ProviderAdmissionStatus.NO_COMPATIBLE_MODEL
        elif self.snapshot.client_for(normalized) is None:
            status = ProviderAdmissionStatus.CLIENT_UNAVAILABLE
        else:
            status = admitted_status(catalog.source)

        compiled = None
        if status in {
            ProviderAdmissionStatus.ADMITTED,
            ProviderAdmissionStatus.ADMITTED_UNVERIFIED,
        }:
            try:
                compiled = compile_admitted_toolset(
                    provider=normalized,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            except Exception as exc:
                from .protocol import ProviderToolCompilationError

                status = (
                    compilation_status(exc)
                    if isinstance(exc, ProviderToolCompilationError)
                    else ProviderAdmissionStatus.PROVIDER_PROTOCOL
                )
        record = next((item for item in records if item.model_id == model), None)
        admission = ProviderCallAdmission(
            provider=normalized,
            operation=operation,
            status=status,
            model=model
            if status
            in {
                ProviderAdmissionStatus.ADMITTED,
                ProviderAdmissionStatus.ADMITTED_UNVERIFIED,
            }
            else None,
            generation_sequence=self.snapshot.generation_for(normalized),
            client=self.snapshot.client_for(normalized),
            compiled_tools=compiled,
            candidate_count=len(candidate_ids),
            embedding_dimension=record.embedding_dimension if record is not None else None,
        )
        self._call_cache[key] = admission
        return admission

    def admit_first(
        self,
        *,
        operation: ProviderOperation,
        prefer: str | None = None,
        expected_embedding_dimension: int | None = None,
        pick_model: ModelPicker,
    ) -> ProviderCallAdmission | None:
        owner = self.snapshot.owner_for(prefer)
        order = ([owner] if owner else []) + [
            provider for provider in self.snapshot.provider_order if provider != owner
        ]
        for provider in order:
            decision = self.admit(
                provider,
                operation=operation,
                prefer=prefer,
                expected_embedding_dimension=expected_embedding_dimension,
                pick_model=pick_model,
            )
            if decision.status in {
                ProviderAdmissionStatus.ADMITTED,
                ProviderAdmissionStatus.ADMITTED_UNVERIFIED,
            }:
                return decision
        return None


def _record_satisfies(record: ProviderModelRecord, requirement: ModelRequirement) -> bool:
    return (
        (not requirement.chat or record.supports("chat"))
        and (not requirement.tools or record.supports("tools"))
        and (not requirement.vision or record.supports("vision"))
    )


def _unavailable_catalog_status():
    from .model_catalog import ModelCatalogStatus

    return ModelCatalogStatus.UNAVAILABLE


__all__ = ["RunProviderAdmission", "RunProviderSnapshot"]
