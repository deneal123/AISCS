"""Base contracts for pluggable agent integrations."""

from __future__ import annotations

import abc
import logging
import time
from typing import Any

from service.infrastructure.memory.diagnostics import log_memory_failure, operation_metadata
from service.shared.memory_outcomes import MemoryWriteResult


class BaseIntegration(abc.ABC):
    """Generic base contract for all agent integrations.

    This class is intended to be reused by multiple integration types
    (memory, external tools, analytics, etc.).
    """

    def __init__(self, *, name: str) -> None:
        self.name = name
        self.logger = logging.getLogger(f"service.infrastructure.memory.{name}")

    @property
    @abc.abstractmethod
    def available(self) -> bool:
        """Whether provider is configured and ready for usage."""

    def _log_operation_start(self, operation: str, **details: Any) -> float:
        started = time.perf_counter()
        metadata = operation_metadata(operation, "started", details)
        self.logger.debug("Memory operation %s started", metadata["operation"], extra=metadata)
        return started

    def _log_operation_success(self, operation: str, started: float, **details: Any) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        metadata = operation_metadata(operation, "completed", details)
        metadata["elapsed_ms"] = max(0.0, elapsed_ms)
        self.logger.info("Memory operation %s completed", metadata["operation"], extra=metadata)

    def _log_operation_failure(self, operation: str, started: float, exc: Exception) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        log_memory_failure(self.logger, operation, exc, warning=True, elapsed_ms=elapsed_ms)


class BaseMemoryIntegration(BaseIntegration, abc.ABC):
    """Specialized base contract for memory integrations."""

    @abc.abstractmethod
    async def get_memory_context(self, *, user_id: str, top_k: int = 5) -> str:
        """Return formatted memory context for prompt enrichment."""

    @abc.abstractmethod
    async def save_messages(
        self,
        *,
        user_id: str,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryWriteResult:
        """Persist conversation fragments/facts into memory provider."""

    @abc.abstractmethod
    async def list_facts(
        self,
        *,
        user_id: str,
        query: str | None = None,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        """Return raw fact-like memory items for a user."""

    @abc.abstractmethod
    async def add_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        fact_value: str,
    ) -> dict[str, Any]:
        """Add a user fact into memory provider and return created item details."""

    @abc.abstractmethod
    async def delete_fact(self, *, user_id: str, fact_id: str) -> bool:
        """Delete a fact by provider ID."""


class NoopMemoryIntegration(BaseMemoryIntegration):
    """Fallback integration used when provider is unavailable."""

    def __init__(self) -> None:
        super().__init__(name="noop_memory")

    @property
    def available(self) -> bool:
        return False

    async def get_memory_context(self, *, user_id: str, top_k: int = 5) -> str:
        return ""

    async def save_messages(
        self,
        *,
        user_id: str,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> MemoryWriteResult:
        return MemoryWriteResult.UNAVAILABLE

    async def list_facts(
        self,
        *,
        user_id: str,
        query: str | None = None,
        top_k: int = 50,
    ) -> list[dict[str, Any]]:
        return []

    async def add_fact(
        self,
        *,
        user_id: str,
        fact_type: str,
        fact_key: str,
        fact_value: str,
    ) -> dict[str, Any]:
        return {}

    async def delete_fact(self, *, user_id: str, fact_id: str) -> bool:
        return False
