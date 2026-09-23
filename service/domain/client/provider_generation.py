"""Lease-based lifecycle for immutable provider client generations.

Credential rotation must not mutate an already running agents request.  Each run
leases the exact client generation it observed at admission time.  Rebuild publishes
the replacement atomically and retires the previous client; the retired client is
closed only after its final run releases the lease.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .model_catalog import ProviderModelCatalog

logger = logging.getLogger(__name__)


class ProviderGenerationStatus(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class ProviderRuntimeGeneration:
    provider: str
    sequence: int
    configuration_digest: str
    client: Any
    status: ProviderGenerationStatus
    catalog: ProviderModelCatalog | None = None


class ProviderGenerationLease:
    """Idempotent reference to one immutable runtime generation."""

    __slots__ = ("_manager", "generation", "_released")

    def __init__(
        self,
        manager: ProviderGenerationManager,
        generation: ProviderRuntimeGeneration,
    ) -> None:
        self._manager = manager
        self.generation = generation
        self._released = False

    @property
    def client(self) -> Any:
        return self.generation.client

    @property
    def sequence(self) -> int:
        return self.generation.sequence

    @property
    def configuration_digest(self) -> str:
        return self.generation.configuration_digest

    @property
    def catalog(self) -> ProviderModelCatalog | None:
        return self.generation.catalog

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._manager.release(self.generation.sequence)


class ProviderGenerationManager:
    """Process-local publisher and drain queue for one provider."""

    def __init__(self, provider: str) -> None:
        self.provider = str(provider).strip().lower()
        self._sequence = 0
        self._current = ProviderRuntimeGeneration(
            provider=self.provider,
            sequence=0,
            configuration_digest="unconfigured",
            client=None,
            status=ProviderGenerationStatus.UNAVAILABLE,
        )
        self._leases: dict[int, int] = {0: 0}
        self._retired: dict[int, ProviderRuntimeGeneration] = {}
        self._close_tasks: set[asyncio.Task[Any]] = set()

    @property
    def current(self) -> ProviderRuntimeGeneration:
        return self._current

    @property
    def retired_count(self) -> int:
        return len(self._retired)

    @property
    def leased_count(self) -> int:
        return sum(self._leases.values())

    def publish(
        self,
        *,
        client: Any,
        configuration_digest: str,
        catalog: ProviderModelCatalog | None = None,
    ) -> ProviderRuntimeGeneration:
        previous = self._current
        self._sequence += 1
        generation = ProviderRuntimeGeneration(
            provider=self.provider,
            sequence=self._sequence,
            configuration_digest=str(configuration_digest),
            client=client,
            status=(
                ProviderGenerationStatus.READY
                if client is not None
                else ProviderGenerationStatus.UNAVAILABLE
            ),
            catalog=catalog,
        )
        self._current = generation
        self._leases.setdefault(generation.sequence, 0)
        if previous.sequence and previous.client is not None and previous.client is not client:
            self._retired[previous.sequence] = previous
            self._close_if_drained(previous.sequence)
        return generation

    def attach_catalog(
        self,
        *,
        sequence: int,
        catalog: ProviderModelCatalog,
    ) -> bool:
        """Publish catalog evidence for future leases without mutating existing ones."""

        current = self._current
        if current.sequence != sequence or current.client is None:
            return False
        self._current = ProviderRuntimeGeneration(
            provider=current.provider,
            sequence=current.sequence,
            configuration_digest=current.configuration_digest,
            client=current.client,
            status=current.status,
            catalog=catalog,
        )
        return True

    def acquire(self) -> ProviderGenerationLease:
        generation = self._current
        self._leases[generation.sequence] = self._leases.get(generation.sequence, 0) + 1
        return ProviderGenerationLease(self, generation)

    def release(self, sequence: int) -> None:
        current = self._leases.get(sequence, 0)
        if current <= 1:
            self._leases[sequence] = 0
        else:
            self._leases[sequence] = current - 1
        self._close_if_drained(sequence)

    def _close_if_drained(self, sequence: int) -> None:
        if self._leases.get(sequence, 0) > 0:
            return
        generation = self._retired.pop(sequence, None)
        if generation is None:
            return
        self._schedule_close(generation.client)
        self._leases.pop(sequence, None)

    def _schedule_close(self, client: Any) -> None:
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is None:
            return
        if inspect.iscoroutinefunction(close):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # There is no safe owner for an async close outside a running loop.
                # The process is already leaving its runtime boundary.
                return
            task = loop.create_task(close())
            self._close_tasks.add(task)
            task.add_done_callback(self._close_tasks.discard)
            return
        try:
            result = close()
        except Exception:  # noqa: BLE001 - diagnostics remain bounded
            logger.warning(
                "provider generation close failed",
                extra={"component": self.provider, "failure_code": "internal"},
            )
            return
        if not inspect.isawaitable(result):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Do not leave a coroutine created by an unusual sync wrapper unclosed.
            close_awaitable = getattr(result, "close", None)
            if callable(close_awaitable):
                close_awaitable()
            return
        task = loop.create_task(result)
        self._close_tasks.add(task)
        task.add_done_callback(self._close_tasks.discard)

    def discard_unpublished(self, client: Any) -> None:
        """Close a prepared client that never became a published generation."""

        if client is not None:
            self._schedule_close(client)

    async def drain(self) -> None:
        """Retire the published client and await every immediately drainable close."""

        current = self._current
        if current.client is not None and current.sequence not in self._retired:
            self._retired[current.sequence] = current
            self._current = ProviderRuntimeGeneration(
                provider=self.provider,
                sequence=current.sequence,
                configuration_digest=current.configuration_digest,
                client=None,
                status=ProviderGenerationStatus.RETIRED,
                catalog=current.catalog,
            )
            self._close_if_drained(current.sequence)

        for sequence in tuple(self._retired):
            self._close_if_drained(sequence)
        if self._close_tasks:
            await asyncio.gather(*tuple(self._close_tasks), return_exceptions=True)


__all__ = [
    "ProviderGenerationLease",
    "ProviderGenerationManager",
    "ProviderGenerationStatus",
    "ProviderRuntimeGeneration",
]
