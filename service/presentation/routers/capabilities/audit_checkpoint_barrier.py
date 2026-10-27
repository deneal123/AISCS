"""Awaited receipt persistence barrier for the private document-audit producer."""

from collections.abc import Callable

from service.domain.usage.ledger import UsageLedger
from service.infrastructure.document_audit.registry import (
    AuditProducerRegistry,
    AuditRegistryUnavailable,
)
from service.presentation.routers.agent.usage_checkpoint import checkpoint_observer


class AuditCheckpointBarrier:
    def __init__(self, registry: AuditProducerRegistry):
        self.registry = registry
        self.ledger: UsageLedger | None = None
        self.latest: dict | None = None
        self.unsubscribe: Callable[[], None] | None = None

    def _emit(self, _key: str, value: object) -> None:
        if not isinstance(value, dict):
            raise AuditRegistryUnavailable()
        self.latest = value

    async def flush(self, ledger: UsageLedger) -> None:
        if self.ledger is None:
            observer = checkpoint_observer(self.registry.attempt, self._emit)
            self.ledger = ledger
            self.unsubscribe = ledger.subscribe(observer)
            observer(ledger.receipts)
        elif self.ledger is not ledger:
            raise AuditRegistryUnavailable()
        await self.registry.require_active()
        if self.latest is not None:
            await self.registry.checkpoint(self.latest)

    def close(self) -> None:
        if self.unsubscribe is not None:
            self.unsubscribe()
            self.unsubscribe = None
