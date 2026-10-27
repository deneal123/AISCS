"""Attempt-owned operational recovery state in the existing Redis service.

Missing state is unknown, never permission to repeat a metered operation.
This registry is not the backend billing ledger and cannot settle an audit.
"""

from __future__ import annotations

import asyncio
import json
import re
from uuid import UUID, uuid4

from service.infrastructure.document_audit.process import owner_stopped, process_owner

TTL_SEC = 30 * 86400
MAX_BYTES = 256 * 1024
_DIGEST = re.compile(r"[a-f0-9]{64}")
_OUTCOMES = frozenset(
    {
        "passed",
        "failed",
        "invalid",
        "page_limit",
        "vision_unavailable",
        "workspace_unavailable",
        "unavailable",
        "timeout",
        "transport",
        "remote",
        "protocol",
        "conflict",
        "expired",
        "cancelled",
        "policy",
        "internal",
    }
)
_CAS = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""


class AuditRegistryUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("document_audit_registry_unavailable")


class AuditProducerRegistry:
    """All mutation requires the original process-local claim token."""

    def __init__(self, redis, *, attempt_id: str, scope_digest: str):
        self.redis = redis
        try:
            self.attempt = str(UUID(attempt_id))
            if _DIGEST.fullmatch(scope_digest) is None:
                raise ValueError
        except (ValueError, TypeError):
            raise AuditRegistryUnavailable() from None
        self.scope = scope_digest
        self.key = "document:audit:producer:" + self.attempt
        self.token: str | None = None

    async def _call(self, method: str, *args, **kwargs):
        if self.redis is None:
            raise AuditRegistryUnavailable()
        try:
            async with asyncio.timeout(2):
                return await getattr(self.redis, method)(*args, **kwargs)
        except Exception:
            raise AuditRegistryUnavailable() from None

    async def claim(self, *, fresh_attempt: bool = False) -> bool:
        """Only a freshly inserted backend attempt may initialize producer state."""
        if fresh_attempt is not True or self.token is not None:
            raise AuditRegistryUnavailable()
        token = uuid4().hex
        state = {
            "schema_version": 2,
            "attempt_id": self.attempt,
            "scope_digest": self.scope,
            "producer_token": token,
            "state": "active",
            "checkpoint": None,
            "result": None,
            "owner": process_owner(),
        }
        if await self._call("set", self.key, self._encode(state), nx=True, ex=TTL_SEC):
            self.token = token
            return True
        # An existing terminal or active attempt is never claimed again.
        await self.read()
        return False

    async def read(self) -> dict | None:
        raw = await self._call("get", self.key)
        if raw is None:
            return None
        state = self._decode(raw)
        if (
            state["state"] == "active"
            and state.get("owner") is not None
            and owner_stopped(state["owner"])
        ):
            state.update(
                state="terminal", result={"status": "internal", "passed": False, "retryable": True}
            )
            if await self._call("eval", _CAS, 1, self.key, raw, self._encode(state), TTL_SEC) != 1:
                latest = await self._call("get", self.key)
                return self._decode(latest)
        return state

    async def snapshot(self) -> dict:
        """Private recovery projection excludes the mutable producer ownership token."""
        state = await self.read()
        if state is None:
            return {"state": "unknown"}
        return {key: state[key] for key in ("state", "checkpoint", "result")}

    async def require_active(self) -> None:
        state = await self.read()
        if state is None or not self._owned(state) or state["state"] != "active":
            raise AuditRegistryUnavailable()

    async def seal(self, result: dict) -> None:
        """Only the original producer may attest completion, never a recovery reader."""
        _validate_result(result)
        raw = await self._call("get", self.key)
        state = self._decode(raw)
        if not self._owned(state):
            raise AuditRegistryUnavailable()
        if result["passed"] and state["checkpoint"] is None:
            raise AuditRegistryUnavailable()
        if state["state"] == "terminal":
            if state["result"] == result:
                return
            raise AuditRegistryUnavailable()
        state.update(state="terminal", result=result)
        if await self._call("eval", _CAS, 1, self.key, raw, self._encode(state), TTL_SEC) != 1:
            raise AuditRegistryUnavailable()

    async def checkpoint(self, payload: dict) -> None:
        """Accept only the canonical observer snapshot, not arbitrary model data."""
        self._validate_checkpoint(payload)
        raw = await self._call("get", self.key)
        state = self._decode(raw)
        if not self._owned(state) or state["state"] != "active":
            raise AuditRegistryUnavailable()
        previous = state["checkpoint"]
        if previous == payload:
            return
        if previous is not None and not _extends(payload, previous):
            raise AuditRegistryUnavailable()
        state["checkpoint"] = payload
        if await self._call("eval", _CAS, 1, self.key, raw, self._encode(state), TTL_SEC) != 1:
            raise AuditRegistryUnavailable()

    def _decode(self, raw) -> dict:
        try:
            if not isinstance(raw, (str, bytes)) or len(raw) > MAX_BYTES:
                raise ValueError
            state = json.loads(raw)
            if (
                not isinstance(state, dict)
                or set(state)
                != (
                    {
                        "schema_version",
                        "attempt_id",
                        "scope_digest",
                        "producer_token",
                        "state",
                        "checkpoint",
                        "result",
                    }
                    | ({"owner"} if state.get("schema_version") == 2 else set())
                )
                or type(state["schema_version"]) is not int
                or state["schema_version"] not in {1, 2}
                or state["attempt_id"] != self.attempt
            ):
                raise ValueError
            if state["scope_digest"] != self.scope or state["state"] not in {"active", "terminal"}:
                raise ValueError
            if (
                not isinstance(state["producer_token"], str)
                or re.fullmatch(r"[a-f0-9]{32}", state["producer_token"]) is None
            ):
                raise ValueError
            if state["checkpoint"] is not None:
                self._validate_checkpoint(state["checkpoint"])
            if state.get("owner") is not None:
                owner = state["owner"]
                if not isinstance(owner, dict) or set(owner) != {"namespace", "pid", "start"}:
                    raise ValueError
                if (
                    not isinstance(owner["namespace"], str)
                    or _DIGEST.fullmatch(owner["namespace"]) is None
                ):
                    raise ValueError
                if type(owner["pid"]) is not int or not 1 <= owner["pid"] <= 2**31 - 1:
                    raise ValueError
                if type(owner["start"]) is not int or owner["start"] < 0:
                    raise ValueError
            if state["state"] == "terminal":
                _validate_result(state["result"])
            elif state["result"] is not None:
                raise ValueError
            return state
        except Exception:
            raise AuditRegistryUnavailable() from None

    def _owned(self, state: dict) -> bool:
        return (
            self.token is not None
            and state["producer_token"] == self.token
            and (state.get("owner") is None or state["owner"] == process_owner())
        )

    def _validate_checkpoint(self, payload: dict) -> None:
        try:
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema_version", "attempt_id", "revision", "receipts"}
                or type(payload["schema_version"]) is not int
                or payload["schema_version"] != 1
            ):
                raise ValueError
            if (
                payload["attempt_id"] != self.attempt
                or type(payload["revision"]) is not int
                or not 1 <= payload["revision"] <= 1_000_000_000
            ):
                raise ValueError
            calls = payload["receipts"]
            if not isinstance(calls, list) or not 1 <= len(calls) <= 256:
                raise ValueError
            ids = set()
            for receipt in calls:
                if (
                    not isinstance(receipt, dict)
                    or set(receipt)
                    != {
                        "receipt_id",
                        "provider",
                        "model",
                        "kind",
                        "prompt",
                        "completion",
                        "estimated",
                    }
                    or receipt["kind"] != "document_visual_audit"
                ):
                    raise ValueError
                if not _identity(receipt["receipt_id"]) or receipt["receipt_id"] in ids:
                    raise ValueError
                ids.add(receipt["receipt_id"])
                if receipt["provider"] not in {
                    None,
                    "gigachat",
                    "openai",
                    "openrouter",
                    "routerai",
                    "mws",
                }:
                    raise ValueError
                if receipt["model"] is not None and not _identity(receipt["model"]):
                    raise ValueError
                if type(receipt["estimated"]) is not bool:
                    raise ValueError
                if any(
                    type(receipt[key]) is not int or not 0 <= receipt[key] <= 1_000_000_000
                    for key in ("prompt", "completion")
                ):
                    raise ValueError
        except Exception:
            raise AuditRegistryUnavailable() from None

    @staticmethod
    def _encode(state: dict) -> str:
        try:
            raw = json.dumps(state, separators=(",", ":"), allow_nan=False)
            if len(raw.encode()) > MAX_BYTES:
                raise ValueError
            return raw
        except Exception:
            raise AuditRegistryUnavailable() from None


def _identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value))
        and not (
            "://" in value
            or value.startswith(("/", "./"))
            or ".." in value.split("/")
            or re.match(r"^[A-Za-z]:/", value)
        )
    )


def _validate_result(result: dict) -> None:
    if not isinstance(result, dict) or set(result) != {"status", "passed", "retryable"}:
        raise AuditRegistryUnavailable()
    if not isinstance(result["status"], str) or result["status"] not in _OUTCOMES:
        raise AuditRegistryUnavailable()
    if type(result["passed"]) is not bool or type(result["retryable"]) is not bool:
        raise AuditRegistryUnavailable()
    if (
        result["passed"] != (result["status"] == "passed")
        or result["passed"]
        and result["retryable"]
    ):
        raise AuditRegistryUnavailable()


def _extends(incoming: dict, previous: dict) -> bool:
    if incoming["revision"] <= previous["revision"] or len(incoming["receipts"]) < len(
        previous["receipts"]
    ):
        return False
    for call, old in zip(incoming["receipts"], previous["receipts"], strict=False):
        if any(call[key] != old[key] for key in ("receipt_id", "model", "provider", "kind")):
            return False
        if call != old and not (
            call["prompt"] + call["completion"] > 0
            and (
                old["prompt"] + old["completion"] == 0 or old["estimated"] and not call["estimated"]
            )
        ):
            return False
    return True
