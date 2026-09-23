"""Event-loop-safe provider model inventory cache with typed provenance."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from service.domain.client.model_catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)

logger = logging.getLogger(__name__)

DEFAULT_FETCH_TIMEOUT_SEC = 12.0
DEFAULT_FALLBACK_TTL_SEC = 30


def _default_fetch(client: Any) -> Awaitable[Any]:
    return client.models.list()


def _default_normalize(response: Any) -> list[str]:
    from service.domain.client.providers.openai_compatible import normalize_model_list

    if not hasattr(response, "data") or not isinstance(response.data, (list, tuple)):
        raise ValueError("malformed model catalog")
    return normalize_model_list(response.data)


class ModelListCache:
    """Cache one provider inventory while preserving discovery provenance.

    A successful empty catalog is cached as an authoritative result. Static fallback
    models are used only when discovery itself failed before any authoritative result
    was observed. No asyncio primitive is stored, so the cache remains safe when
    Celery executes calls on different event loops.
    """

    def __init__(
        self,
        *,
        name: str,
        provider: str | None = None,
        ttl_fn: Callable[[], int],
        fallback: list[str] | None = None,
        fetch_timeout_sec: float = DEFAULT_FETCH_TIMEOUT_SEC,
        fallback_ttl_sec: int = DEFAULT_FALLBACK_TTL_SEC,
        capability_profiles: tuple[tuple[str, tuple[str, ...]], ...] = (),
        embedding_dimensions: tuple[tuple[str, int], ...] = (),
    ) -> None:
        self._name = name
        self._provider = (provider or name).strip().lower()
        self._ttl_fn = ttl_fn
        self._fallback = tuple(fallback or ())
        self._timeout = fetch_timeout_sec
        self._fallback_ttl = fallback_ttl_sec
        self._capability_profiles = {
            model: frozenset(capabilities) for model, capabilities in capability_profiles
        }
        self._embedding_dimensions = {
            model: int(dimension) for model, dimension in embedding_dimensions
        }
        self._entries: dict[str, tuple[ProviderModelCatalog, float]] = {}

    async def get(
        self,
        *,
        client: Any,
        fetch: Callable[[Any], Awaitable[Any]] | None = None,
        normalize: Callable[[Any], list[str]] | None = None,
        force_refresh: bool = False,
        configuration_key: str = "",
    ) -> list[str]:
        snapshot = await self.get_snapshot(
            client=client,
            fetch=fetch,
            normalize=normalize,
            force_refresh=force_refresh,
            configuration_key=configuration_key,
        )
        return list(snapshot.models)

    async def get_snapshot(
        self,
        *,
        client: Any,
        fetch: Callable[[Any], Awaitable[Any]] | None = None,
        normalize: Callable[[Any], list[str]] | None = None,
        force_refresh: bool = False,
        configuration_key: str = "",
    ) -> ProviderModelCatalog:
        """Return inventory and bounded provenance without exception text."""
        fetch = fetch or _default_fetch
        normalize = normalize or _default_normalize
        if client is None:
            return self._fallback_snapshot()

        now = time.monotonic()
        cached = self._entries.get(configuration_key)
        if not force_refresh and cached is not None and now < cached[1]:
            return cached[0]

        try:
            response = await asyncio.wait_for(fetch(client), timeout=self._timeout)
        except Exception as exc:
            return self._degraded_snapshot(now, _fetch_failure_status(exc), configuration_key)
        try:
            models = tuple(normalize(response))
        except Exception:
            return self._degraded_snapshot(now, ModelCatalogStatus.MALFORMED, configuration_key)

        snapshot = ProviderModelCatalog(
            provider=self._provider,
            models=models,
            source=ModelCatalogSource.LIVE,
            status=ModelCatalogStatus.AVAILABLE if models else ModelCatalogStatus.EMPTY,
            fresh=True,
            records=self._records_from_response(response, models),
        )
        self._store(configuration_key, snapshot, now + max(1, int(self._ttl_fn())))
        return snapshot

    def _degraded_snapshot(
        self,
        now: float,
        status: ModelCatalogStatus,
        configuration_key: str,
    ) -> ProviderModelCatalog:
        logger.warning(
            "provider model list unavailable",
            extra={"component": self._name, "failure_code": status.value},
        )
        cached = self._entries.get(configuration_key)
        previous = cached[0] if cached is not None else None
        if previous is not None and previous.authoritative:
            snapshot = ProviderModelCatalog(
                provider=self._provider,
                models=previous.models,
                source=ModelCatalogSource.STALE,
                status=status,
                fresh=False,
                records=previous.records,
            )
        else:
            snapshot = self._fallback_snapshot(status=status)
        self._store(configuration_key, snapshot, now + self._fallback_ttl)
        return snapshot

    def _fallback_snapshot(
        self,
        *,
        status: ModelCatalogStatus = ModelCatalogStatus.UNAVAILABLE,
    ) -> ProviderModelCatalog:
        return ProviderModelCatalog(
            provider=self._provider,
            models=self._fallback,
            source=ModelCatalogSource.STATIC_FALLBACK,
            status=status,
            fresh=False,
            records=tuple(
                ProviderModelRecord(
                    model_id=model,
                    capabilities=self._capability_profiles.get(model, frozenset()),
                    evidence_source=CapabilityEvidenceSource.STATIC_FALLBACK,
                    embedding_dimension=self._embedding_dimensions.get(model),
                )
                for model in self._fallback
            ),
        )

    def _records_from_response(
        self,
        response: Any,
        models: tuple[str, ...],
    ) -> tuple[ProviderModelRecord, ...]:
        raw_items = getattr(response, "data", ())
        raw_by_id = {
            str(_item_field(item, "id") or ""): item
            for item in raw_items
            if str(_item_field(item, "id") or "")
        }
        records: list[ProviderModelRecord] = []
        for model in models:
            declared = self._capability_profiles.get(model)
            if declared:
                records.append(
                    ProviderModelRecord(
                        model_id=model,
                        capabilities=declared,
                        evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
                        embedding_dimension=self._embedding_dimensions.get(model),
                    )
                )
                continue
            capabilities = _provider_capabilities(raw_by_id.get(model))
            dimension = _provider_embedding_dimension(raw_by_id.get(model))
            records.append(
                ProviderModelRecord(
                    model_id=model,
                    capabilities=capabilities,
                    evidence_source=(
                        CapabilityEvidenceSource.PROVIDER_METADATA
                        if capabilities
                        else CapabilityEvidenceSource.UNKNOWN
                    ),
                    embedding_dimension=dimension,
                )
            )
        return tuple(records)

    def clear(self) -> None:
        self._entries.clear()

    def _store(self, key: str, snapshot: ProviderModelCatalog, expires_at: float) -> None:
        self._entries[key] = (snapshot, expires_at)
        # Credential rotations are rare; bounding old generations prevents an admin
        # repeatedly rotating keys from growing process memory without limit.
        while len(self._entries) > 4:
            self._entries.pop(next(iter(self._entries)))


def _fetch_failure_status(exc: Exception) -> ModelCatalogStatus:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return ModelCatalogStatus.TIMEOUT
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return ModelCatalogStatus.AUTH
    response = getattr(exc, "response", None)
    if getattr(response, "status_code", None) in {401, 403}:
        return ModelCatalogStatus.AUTH
    return ModelCatalogStatus.UNAVAILABLE


def _provider_capabilities(item: Any) -> frozenset[str]:
    """Read only explicit capability metadata from a provider model record."""

    if item is None:
        return frozenset()
    raw = _item_field(item, "capabilities")
    raw_values = raw if isinstance(raw, (list, tuple, set, frozenset)) else ()
    capabilities = {
        str(value).strip().lower()
        for value in raw_values
        if str(value).strip().lower()
        in {"chat", "tools", "vision", "image_output", "embeddings", "transcription"}
    }
    supported = _item_field(item, "supported_parameters")
    supported_values = supported if isinstance(supported, (list, tuple, set, frozenset)) else ()
    if "tools" in supported_values:
        capabilities.add("tools")
    architecture = _item_field(item, "architecture")
    if not isinstance(architecture, dict):
        architecture = {}
    if "image" in (architecture.get("input_modalities") or ()):
        capabilities.add("vision")
    if "image" in (architecture.get("output_modalities") or ()):
        capabilities.add("image_output")
    model_type = str(_item_field(item, "type") or "").strip().lower()
    if model_type in {"embedding", "embeddings"}:
        capabilities.add("embeddings")
    input_modalities = set(architecture.get("input_modalities") or ())
    output_modalities = set(architecture.get("output_modalities") or ())
    if "audio" in input_modalities and "text" in output_modalities:
        capabilities.add("transcription")
    return frozenset(capabilities)


def _provider_embedding_dimension(item: Any) -> int | None:
    if item is None:
        return None
    for field in ("embedding_dimension", "dimensions", "dimension"):
        value = _item_field(item, field)
        if isinstance(value, int) and value > 0:
            return value
    return None


def _item_field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


__all__ = ["ModelListCache"]
