"""Private, bounded progress evidence; model prose never confirms an effect."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _operation_identity(name: str, parsed: Any, canonical: str) -> str:
    if not isinstance(parsed, dict):
        return canonical
    if name in {"ide_read_file", "ide_write_file", "ide_edit_file", "ide_create_directory"}:
        return parsed["path"] if isinstance(parsed.get("path"), str) else canonical
    if (
        name == "ide_run_command"
        and parsed.get("profile") in ("python_script", "unittest", "pytest")
        and isinstance(parsed.get("criterion_id"), str)
        and parsed["criterion_id"]
        and isinstance(parsed.get("target"), str)
        and (parsed.get("expected_stdout") is None or isinstance(parsed["expected_stdout"], str))
    ):
        # Совпадает с backend verification recipe плюс criterion_id. Таймаут и
        # необязательный command=null не меняют проверку. Это лишь снятие guard:
        # успешный outcome и актуальное evidence по-прежнему выдаёт исполнитель.
        return json.dumps(
            {
                key: parsed.get(key)
                for key in ("criterion_id", "profile", "target", "expected_stdout")
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    return canonical


@dataclass(slots=True)
class TaskProgress:
    """One task's loop guard, independent of provider and tool-name conventions.

    Fingerprints contain neither arguments nor output. They are not an idempotency
    journal: an unknown mutation must be reconciled by its authoritative service.
    """

    active: bool = False
    stop_reason: str = ""
    rounds: int = 0
    repairs: int = 0
    _observations: dict[str, int] = field(default_factory=dict, repr=False)
    _revision: str = field(default="", repr=False)
    _failed_operations: set[str] = field(default_factory=set, repr=False)

    def claim_round(self, *, limit: int | None = None) -> bool:
        if self.active and limit is not None and self.rounds >= limit:
            self.stop_reason = "round_limit"
            return False
        self.rounds += 1
        return True

    def observe(self, call: dict[str, Any], outcome: Any, *, revision: str) -> None:
        if not self.active:
            return
        if getattr(outcome, "pending", False):
            return  # An authoritative running process is not an identical failed action.
        name = str(call.get("name") or "unknown")[:256]
        if revision != self._revision:
            self._observations.clear()
            self._revision = revision
            if self.stop_reason == "no_progress":
                self.stop_reason = ""
        arguments = call.get("arguments", "{}")
        parsed = None
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
            canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        except (ValueError, TypeError, RecursionError):
            canonical = str(arguments)
        # IDE repairs may change content/base digest without changing the target.
        # Different files remain independent obligations, even for the same tool.
        identity = _operation_identity(name, parsed, canonical)
        operation = hashlib.sha256(json.dumps([name, identity]).encode()).hexdigest()
        if outcome.succeeded or outcome.reused:
            self._failed_operations.discard(operation)
        elif len(self._failed_operations) < 128:
            self._failed_operations.add(operation)
        value = json.dumps(
            [call.get("name"), canonical, outcome.status, outcome.failure_code, outcome.text],
            ensure_ascii=False,
        )
        fingerprint = hashlib.sha256(value.encode()).hexdigest()
        if len(self._observations) >= 128 and fingerprint not in self._observations:
            self._observations.pop(next(iter(self._observations)))
        count = self._observations.get(fingerprint, 0) + 1
        self._observations[fingerprint] = count
        if count >= 3:
            self.stop_reason = "no_progress"

    def result(self, *, cancelled: bool, unconfirmed: bool) -> dict[str, Any] | None:
        """Expose only why execution stopped, never infer semantic task success."""
        if not self.active:
            return None
        reason = "cancelled" if cancelled else self.stop_reason
        if unconfirmed:
            reason = "unconfirmed_effect"
        if not reason and self._failed_operations:
            reason = "tool_failed"
        if not reason:
            return None
        return {
            "schema_version": 1,
            "status": "cancelled" if cancelled else "partial",
            "blocker": reason,
            "rounds": self.rounds,
            "repair_cycles": self.repairs,
            "verified": False,
        }
