"""Typed, privacy-safe snapshots of one provider's model inventory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ModelCatalogSource(StrEnum):
    """Where the inventory used for qualification came from."""

    LIVE = "live"
    STALE = "stale"
    STATIC_FALLBACK = "static_fallback"


class ModelCatalogStatus(StrEnum):
    """Bounded discovery result; provider response details are intentionally absent."""

    AVAILABLE = "available"
    EMPTY = "empty"
    AUTH = "auth"
    TIMEOUT = "timeout"
    MALFORMED = "malformed"
    UNAVAILABLE = "unavailable"


class CapabilityEvidenceSource(StrEnum):
    """Bounded evidence used to admit one model capability."""

    PROVIDER_METADATA = "provider_metadata"
    LOCAL_PROFILE = "local_profile"
    TRUSTED_CATALOG = "trusted_catalog"
    STATIC_FALLBACK = "static_fallback"
    UNKNOWN = "unknown"


class ModelCapability(StrEnum):
    """Provider-neutral operations evidenced for one opaque model ID."""

    CHAT = "chat"
    TOOLS = "tools"
    VISION = "vision"
    IMAGE_OUTPUT = "image_output"
    EMBEDDINGS = "embeddings"
    TRANSCRIPTION = "transcription"


@dataclass(frozen=True, slots=True)
class ProviderModelRecord:
    """Opaque model identifier plus positively evidenced runtime capabilities.

    Capability absence means ``unknown`` rather than unsupported.  Admission is
    deliberately fail-closed: an unknown capability never satisfies a requirement.
    """

    model_id: str
    capabilities: frozenset[str] = frozenset()
    evidence_source: CapabilityEvidenceSource = CapabilityEvidenceSource.UNKNOWN
    embedding_dimension: int | None = None

    def supports(self, capability: str) -> bool:
        return str(capability) in self.capabilities


@dataclass(frozen=True, slots=True)
class ProviderModelCatalog:
    """Immutable inventory snapshot used by selection and health projection.

    ``models`` may be empty.  A successful empty response is authoritative and must
    not be confused with a transport failure that activates a static fallback.
    """

    provider: str
    models: tuple[str, ...]
    source: ModelCatalogSource
    status: ModelCatalogStatus
    fresh: bool
    records: tuple[ProviderModelRecord, ...] = ()

    @property
    def model_count(self) -> int:
        return len(self.models)

    @property
    def authoritative(self) -> bool:
        return self.source in {ModelCatalogSource.LIVE, ModelCatalogSource.STALE}

    @property
    def discovery_available(self) -> bool:
        return self.status in {ModelCatalogStatus.AVAILABLE, ModelCatalogStatus.EMPTY}

    def model_records(self) -> tuple[ProviderModelRecord, ...]:
        """Return records for all IDs, preserving compatibility snapshots safely."""

        by_id = {record.model_id: record for record in self.records}
        return tuple(by_id.get(model, ProviderModelRecord(model_id=model)) for model in self.models)


__all__ = [
    "CapabilityEvidenceSource",
    "ModelCapability",
    "ModelCatalogSource",
    "ModelCatalogStatus",
    "ProviderModelCatalog",
    "ProviderModelRecord",
]
