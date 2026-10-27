"""Private canonical accounting checkpoint; never an AgentEvent or terminal result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from service.infrastructure.agents_client.contracts.usage_identity import safe_usage_identity
from service.infrastructure.agents_client.contracts.usage_kinds import SERVICE_USAGE_KINDS
from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.jobs.persistence.transitions import (
    EXECUTION_KEY,
    RECOVERY_KEYS,
    USAGE_JOURNAL_KEY,
)

_FIELDS = frozenset(
    {"receipt_id", "provider", "model", "kind", "prompt", "completion", "estimated"}
)
_MAX_CALLS = 4096
_MAX_TOKENS = 1_000_000_000
_PROVIDERS = frozenset({"openai", "openrouter", "routerai", "gigachat", "mws", "local"})
_KINDS = SERVICE_USAGE_KINDS | frozenset(
    {
        "chat",
        "pdf_authoring",
        "research_synthesis",
        "research_repair",
        "audio_postprocess",
        "multi_intent_usage",
        "empty_response_usage",
        "other",
    }
)


def _identity(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    normalized = safe_usage_identity(value)
    if normalized is None:
        raise ValueError
    return normalized


@dataclass(frozen=True, slots=True)
class JournalReceipt:
    receipt_id: str
    provider: str | None
    model: str | None
    kind: str | None
    prompt: int
    completion: int
    estimated: bool

    @classmethod
    def decode(cls, value: Any) -> JournalReceipt:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError
        for name in ("prompt", "completion"):
            if type(value[name]) is not int or not 0 <= value[name] <= _MAX_TOKENS:
                raise ValueError
        if type(value["estimated"]) is not bool:
            raise ValueError
        if value["provider"] is not None and value["provider"] not in _PROVIDERS:
            raise ValueError
        if value["kind"] is not None and value["kind"] not in _KINDS:
            raise ValueError
        receipt_id = _identity(value["receipt_id"])
        assert receipt_id is not None
        return cls(
            receipt_id,
            _identity(value["provider"], nullable=True),
            _identity(value["model"], nullable=True),
            _identity(value["kind"], nullable=True),
            value["prompt"],
            value["completion"],
            value["estimated"],
        )

    def payload(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _FIELDS}

    def refines(self, previous: JournalReceipt) -> bool:
        identity = (self.receipt_id, self.provider, self.model, self.kind)
        old_identity = (previous.receipt_id, previous.provider, previous.model, previous.kind)
        if identity != old_identity:
            return False
        if self == previous:
            return True
        return self.prompt + self.completion > 0 and (
            previous.prompt + previous.completion == 0
            or (previous.estimated and not self.estimated)
        )


@dataclass(frozen=True, slots=True)
class UsageJournal:
    attempt_id: str
    revision: int
    receipts: tuple[JournalReceipt, ...]

    @classmethod
    def decode(cls, value: Any) -> UsageJournal:
        try:
            if not isinstance(value, dict) or set(value) != {
                "schema_version",
                "attempt_id",
                "revision",
                "receipts",
            }:
                raise ValueError
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValueError
            if type(value["revision"]) is not int or not 1 <= value["revision"] <= _MAX_TOKENS:
                raise ValueError
            if (
                not isinstance(value["receipts"], list)
                or not 1 <= len(value["receipts"]) <= _MAX_CALLS
            ):
                raise ValueError
            attempt = str(UUID(value["attempt_id"]))
            receipts = tuple(JournalReceipt.decode(item) for item in value["receipts"])
            if len({item.receipt_id for item in receipts}) != len(receipts):
                raise ValueError
            return cls(attempt, value["revision"], receipts)
        except Exception:
            raise JobStateUnavailable("Usage checkpoint unavailable") from None

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "attempt_id": self.attempt_id,
            "revision": self.revision,
            "receipts": [item.payload() for item in self.receipts],
        }

    def extends(self, previous: UsageJournal) -> bool:
        return (
            self.attempt_id == previous.attempt_id
            and self.revision > previous.revision
            and len(self.receipts) >= len(previous.receipts)
            and all(
                item.refines(old)
                for item, old in zip(self.receipts, previous.receipts, strict=False)
            )
        )


async def stage_usage_journal(
    repository: Any,
    session: Any,
    *,
    job_id: UUID,
    owner_id: UUID,
    thread_id: str,
    payload: Any,
) -> bool:
    """Stage under the owned row lock. Caller owns commit/ACK and transport policy.

    This function has no event, charge, model invocation or implicit terminal
    promotion. A replay acknowledges only exactly identical canonical data.
    """
    try:
        journal = UsageJournal.decode(payload)
        row = await repository.lock_prepared_turn(job_id, owner_id, session=session)
        if row is None or row["status"] != ProcessingStatus.PROCESSING:
            raise ValueError
        stored = row.get("payload") or {}
        if stored.get("thread_id") != thread_id or stored.get(EXECUTION_KEY) != journal.attempt_id:
            raise ValueError
        if USAGE_JOURNAL_KEY in stored:
            previous = UsageJournal.decode(stored[USAGE_JOURNAL_KEY])
            if journal == previous:
                return False
            if not journal.extends(previous):
                raise ValueError
        # Accepted result and recovery facts freeze their canonical accounting.
        # A delayed checkpoint may ACK identical data, never revise settlement.
        if any(key in stored for key in RECOVERY_KEYS):
            raise ValueError
        saved = await repository.stage_usage_journal(
            job_id,
            owner_id,
            thread_id,
            journal.attempt_id,
            json.dumps(journal.payload(), separators=(",", ":")),
            session=session,
        )
        if saved is not True:
            raise ValueError
        return True
    except Exception:
        raise JobStateUnavailable("Usage checkpoint unavailable") from None
