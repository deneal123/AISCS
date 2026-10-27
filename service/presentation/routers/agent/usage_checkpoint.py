"""Opt-in private NDJSON checkpoint; never an AgentEvent or public metadata."""

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from service.domain.usage.ledger import UsageLedger, UsageReceipt
from service.protocol_manifest import load_protocol_manifest

_PROTOCOL = load_protocol_manifest()
USAGE_KEY = _PROTOCOL.usage_checkpoint_key
ATTEMPT_HEADER = _PROTOCOL.usage_checkpoint_header


def serialize_frame(item: Any, serializer: Any, job_id: str) -> str:
    """Separate internal records from the safe AgentEvent serialization seam."""
    if isinstance(item, tuple):
        key, value = item
        payload = {key: value}
    else:
        payload = serializer.serialize(event=item, job_id=job_id)
    return json.dumps(payload, ensure_ascii=False, default=lambda _value: None) + "\n"


def normalize_attempt(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def checkpoint_observer(attempt: str, emit: Callable[[str, object], None]):
    revision = 0
    previous = None

    def changed(receipts: tuple[UsageReceipt, ...]) -> None:
        nonlocal revision, previous
        calls = [
            {
                "receipt_id": item.receipt_id,
                "provider": item.provider,
                "model": item.model,
                "kind": item.kind,
                "prompt": item.prompt,
                "completion": item.completion,
                "estimated": item.estimated,
            }
            for item in receipts
            if item.billable
        ]
        if not calls or calls == previous:
            return
        previous = calls
        revision += 1
        emit(
            USAGE_KEY,
            {"schema_version": 1, "attempt_id": attempt, "revision": revision, "receipts": calls},
        )

    return changed


class UsageCheckpointBinding:
    """Own exactly one scoped ledger subscription and its deterministic cleanup."""

    def __init__(self, attempt: object, recovery: Any, emit: Callable[[str, object], None]):
        self.attempt = normalize_attempt(attempt)
        self.recovery = recovery
        self.emit = emit
        self.unsubscribe: Callable[[], None] | None = None
        self.ledger: UsageLedger | None = None

    def bind(self, ledger: UsageLedger) -> None:
        self.recovery.bind_usage_ledger(ledger)
        if self.ledger is ledger:
            return
        self.ledger = ledger
        if self.attempt:
            self.unsubscribe = ledger.subscribe(checkpoint_observer(self.attempt, self.emit))

    def close(self) -> None:
        if self.unsubscribe is not None:
            self.unsubscribe()
            self.unsubscribe = None
        self.ledger = None
