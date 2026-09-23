"""Ephemeral, privacy-bounded coordination for a single chat workspace.

The workspace container deliberately cannot reach Redis.  This module is the
only owner of collaboration state and exposes small, deterministic operations
to HTTP/UI and to the signed sidecar coordinator endpoint.  It stores neither
chat prompts nor command/file contents in activity records.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from service.services.chat.application.workspace_event_projection import (
    publish_workspace_invalidation,
)

ROLE_UI = "ui"
ROLE_AGENT = "agent"
ActorRole = Literal["ui", "agent"]

LEASE_TTL_SEC = 30
RUN_TTL_SEC = 120
MAX_ISSUES = 100
MAX_ACTIVITY = 80
MAX_ISSUE_TITLE = 180
MAX_ISSUE_BODY = 4_000
MAX_PATH = 1_024
SAFE_ACTIVITY_KINDS = frozenset(
    {
        "lease_acquired",
        "lease_released",
        "file_saved",
        "library_copied",
        "issue_created",
        "issue_updated",
        "issue_resolved",
        "issue_stale",
        "agent_started",
        "agent_waiting",
        "agent_paused",
        "agent_resumed",
        "agent_cancelled",
        "workspace_recovered",
    }
)
SAFE_MUTATIONS = frozenset({"exec", "import", "write", "snapshot", "revert", "policy"})
SAFE_CONTROL_STATES = frozenset({"running", "pause_requested", "paused", "cancelled"})


class CollaborationError(Exception):
    code = "workspace_unavailable"


class CollaborationUnavailable(CollaborationError):
    """Redis or the coordinator cannot safely make a mutation decision."""


class CollaborationConflict(CollaborationError):
    code = "workspace_conflict"


class CollaborationPaused(CollaborationError):
    code = "workspace_paused"


class CollaborationCancelled(CollaborationError):
    code = "workspace_cancelled"


class CollaborationForbidden(CollaborationError):
    code = "workspace_forbidden"


@dataclass(frozen=True, slots=True)
class WorkspaceCapability:
    workspace_id: str
    actor_id: str
    role: ActorRole
    expires_at: int
    run_id: str = ""
    version: int = 1

    def as_payload(self) -> dict[str, Any]:
        return {
            "v": self.version,
            "w": self.workspace_id,
            "a": self.actor_id,
            "r": self.role,
            "e": self.expires_at,
            "n": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class Lease:
    path: str
    actor_id: str
    role: ActorRole
    fence: int
    expires_at: int

    def public(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "holder": "agent" if self.role == ROLE_AGENT else "you",
            "fence": self.fence,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceIssue:
    issue_id: str
    path: str
    start_line: int
    end_line: int
    revision: str
    title: str
    body: str
    status: Literal["open", "resolved", "stale"]
    created_at: int
    updated_at: int

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> int:
    return int(time.time())


def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret() -> bytes:
    value = str(os.environ.get("WORKSPACE_COORDINATION_SECRET") or "").strip()
    if not value:
        raise CollaborationUnavailable("workspace coordination secret is not configured")
    return value.encode("utf-8")


def mint_capability(
    workspace_id: str,
    *,
    role: ActorRole,
    actor_seed: str,
    expires_at: int | float,
    run_id: str = "",
) -> str:
    """Mint a short opaque capability; user identifiers never cross the wire raw."""
    if role not in {ROLE_UI, ROLE_AGENT}:
        raise ValueError("unsupported workspace actor role")
    payload = WorkspaceCapability(
        workspace_id=str(workspace_id),
        actor_id=_opaque(f"{role}:{actor_seed}"),
        role=role,
        expires_at=max(_now() + 1, int(expires_at)),
        run_id=_opaque(run_id) if run_id else "",
    ).as_payload()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(_secret(), raw, hashlib.sha256).digest()
    return f"v1.{_b64(raw)}.{_b64(signature)}"


def verify_capability(value: str, *, required_role: ActorRole | None = None) -> WorkspaceCapability:
    try:
        version, encoded, supplied = str(value).split(".", 2)
        raw = _unb64(encoded)
        signature = _unb64(supplied)
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise CollaborationForbidden("invalid workspace capability") from None
    expected = hmac.new(_secret(), raw, hashlib.sha256).digest()
    if version != "v1" or not hmac.compare_digest(signature, expected):
        raise CollaborationForbidden("invalid workspace capability")
    try:
        capability = WorkspaceCapability(
            workspace_id=str(payload["w"]),
            actor_id=str(payload["a"]),
            role=str(payload["r"]),
            expires_at=int(payload["e"]),
            run_id=str(payload.get("n") or ""),
            version=int(payload.get("v") or 1),
        )
    except (KeyError, TypeError, ValueError):
        raise CollaborationForbidden("invalid workspace capability") from None
    if (
        not capability.workspace_id
        or capability.role not in {ROLE_UI, ROLE_AGENT}
        or capability.expires_at <= _now()
        or (required_role is not None and capability.role != required_role)
    ):
        raise CollaborationForbidden("expired workspace capability")
    return capability


async def _call(redis: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    if redis is None:
        raise CollaborationUnavailable("workspace collaboration is unavailable")
    try:
        result = getattr(redis, method)(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    except CollaborationError:
        raise
    except Exception as exc:  # redis protocol/transport details are deliberately not exposed
        raise CollaborationUnavailable("workspace collaboration is unavailable") from exc


def _decode(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _safe_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    if not path or len(path) > MAX_PATH or path.startswith("/") or "\x00" in path:
        raise CollaborationConflict("invalid workspace path")
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise CollaborationConflict("invalid workspace path")
    return path


class WorkspaceCollaborationStore:
    """Redis state store with absolute expiry inherited from the sandbox binding."""

    def __init__(
        self, redis: Any, *, workspace_id: str, expires_at: int | float, thread_id: str = ""
    ) -> None:
        self.redis = redis
        self.workspace_id = str(workspace_id)
        self.thread_id = str(thread_id)
        self.expires_at = max(_now() + 1, int(expires_at))
        self.prefix = f"workspace:collab:{self.workspace_id}"

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}:{suffix}"

    def _ttl(self, desired: int | float | None = None) -> int:
        remaining = max(1, self.expires_at - _now())
        return min(remaining, int(desired or remaining))

    async def _set_json(self, key: str, payload: Any, *, ttl: int | float | None = None) -> None:
        await _call(
            self.redis,
            "set",
            key,
            json.dumps(payload, separators=(",", ":")),
            ex=self._ttl(ttl),
        )

    async def _get_json(self, key: str, default: Any) -> Any:
        return _decode(await _call(self.redis, "get", key), default)

    async def initialize(self) -> None:
        meta_key = self._key("meta")
        existing = await _call(self.redis, "get", meta_key)
        if existing is None:
            await self._set_json(meta_key, {"expires_at": self.expires_at, "v": 1})
        else:
            # Never extend an existing collaboration object beyond the sandbox expiry.
            await _call(self.redis, "expire", meta_key, self._ttl())

    async def _publish(self, kind: str, *, count: int = 1) -> None:
        if kind not in SAFE_ACTIVITY_KINDS:
            return
        payload = {"kind": kind, "at": _now(), "count": max(1, min(int(count), 999))}
        activity = self._key("activity")
        await _call(self.redis, "lpush", activity, json.dumps(payload, separators=(",", ":")))
        await _call(self.redis, "ltrim", activity, 0, MAX_ACTIVITY - 1)
        await _call(self.redis, "expire", activity, self._ttl())
        await _call(
            self.redis,
            "publish",
            self._key("events"),
            json.dumps(payload, separators=(",", ":")),
        )
        await publish_workspace_invalidation(
            self.redis,
            thread_id=self.thread_id,
            action=kind,
            state=(await self.control_state()).get("state", "running"),
            revision_changed=kind in {"file_saved", "library_copied", "issue_stale"},
        )

    async def record_activity(self, kind: str, *, count: int = 1) -> None:
        """Append one allowlisted room activity without retaining operation data."""
        await self.initialize()
        await self._publish(kind, count=count)

    async def snapshot(self, *, revision: str = "") -> dict[str, Any]:
        await self.initialize()
        issues = await self.list_issues(include_resolved=True)
        leases = await self.list_leases()
        control = await self.control_state()
        raw = await _call(self.redis, "lrange", self._key("activity"), 0, MAX_ACTIVITY - 1)
        activity = [_decode(item, {}) for item in (raw or [])]
        return {
            "revision": str(revision or ""),
            "issues": issues,
            "leases": leases,
            "control": control,
            "activity": [item for item in activity if isinstance(item, dict)],
            "expires_at": self.expires_at,
        }

    async def control_state(self) -> dict[str, Any]:
        value = await self._get_json(self._key("control"), {"state": "running", "version": 0})
        state = str(value.get("state") or "running") if isinstance(value, dict) else "running"
        return {
            "state": state if state in SAFE_CONTROL_STATES else "running",
            "version": int(value.get("version") or 0) if isinstance(value, dict) else 0,
        }

    async def set_control(self, action: Literal["pause", "resume", "cancel"]) -> dict[str, Any]:
        current = await self.control_state()
        transitions = {
            "pause": "pause_requested" if current["state"] == "running" else current["state"],
            "resume": (
                "running" if current["state"] in {"pause_requested", "paused"} else current["state"]
            ),
            "cancel": "cancelled",
        }
        next_state = transitions[action]
        updated = {"state": next_state, "version": current["version"] + 1}
        await self._set_json(self._key("control"), updated)
        activity = {
            "pause": "agent_waiting",
            "resume": "agent_resumed",
            "cancel": "agent_cancelled",
        }
        await self._publish(activity[action])
        return updated

    async def register_agent_run(self, task_id: str) -> None:
        """Bind the currently running worker to this ephemeral room.

        The task identifier stays in Redis only.  It is intentionally absent
        from snapshots, stream payloads and activity so the room control API
        can request the existing cooperative cancellation seam without
        exposing worker internals to the browser.
        """
        value = str(task_id or "").strip()
        if not value or len(value) > 128:
            return
        await self._set_json(self._key("active_run"), {"task_id": value}, ttl=RUN_TTL_SEC)
        await self.record_activity("agent_started")

    async def active_agent_run(self) -> str:
        value = await self._get_json(self._key("active_run"), {})
        task_id = str(value.get("task_id") or "") if isinstance(value, dict) else ""
        return task_id[:128]

    async def clear_agent_run(self, task_id: str) -> None:
        value = await self._get_json(self._key("active_run"), {})
        active = str(value.get("task_id") or "") if isinstance(value, dict) else ""
        if active and hmac.compare_digest(active, str(task_id or "")):
            await _call(self.redis, "delete", self._key("active_run"))

    async def agent_safe_boundary(self, capability: WorkspaceCapability) -> dict[str, Any]:
        if capability.role != ROLE_AGENT:
            raise CollaborationForbidden("agent capability required")
        state = await self.control_state()
        if state["state"] == "cancelled":
            raise CollaborationCancelled("workspace run was cancelled")
        if state["state"] == "pause_requested":
            await self._set_json(self._key("control"), {**state, "state": "paused"})
            await self._publish("agent_paused")
            raise CollaborationPaused("workspace run is paused")
        if state["state"] == "paused":
            raise CollaborationPaused("workspace run is paused")
        return state

    async def acquire_lease(self, capability: WorkspaceCapability, path: str) -> Lease:
        normalized = _safe_path(path)
        if capability.role == ROLE_AGENT:
            await self.agent_safe_boundary(capability)
        else:
            await self.initialize()
        key = self._key(f"lease:{hashlib.sha256(normalized.encode()).hexdigest()}")
        now = _now()
        raw = await _call(self.redis, "get", key)
        existing = _decode(raw, {})
        if isinstance(existing, dict) and existing.get("actor_id") == capability.actor_id:
            lease = Lease(
                path=normalized,
                actor_id=capability.actor_id,
                role=capability.role,
                fence=int(existing.get("fence") or 1),
                expires_at=now + self._ttl(LEASE_TTL_SEC),
            )
            await self._set_json(key, asdict(lease), ttl=LEASE_TTL_SEC)
            return lease
        if raw is not None:
            raise CollaborationConflict("workspace path is being edited")
        fence = await _call(self.redis, "incr", self._key("lease_fence"))
        lease = Lease(
            path=normalized,
            actor_id=capability.actor_id,
            role=capability.role,
            fence=int(fence),
            expires_at=now + self._ttl(LEASE_TTL_SEC),
        )
        acquired = await _call(
            self.redis,
            "set",
            key,
            json.dumps(asdict(lease), separators=(",", ":")),
            nx=True,
            ex=self._ttl(LEASE_TTL_SEC),
        )
        if not acquired:
            raise CollaborationConflict("workspace path is being edited")
        await self._publish("lease_acquired")
        return lease

    async def renew_lease(self, capability: WorkspaceCapability, path: str, fence: int) -> Lease:
        normalized = _safe_path(path)
        key = self._key(f"lease:{hashlib.sha256(normalized.encode()).hexdigest()}")
        existing = _decode(await _call(self.redis, "get", key), {})
        if (
            not isinstance(existing, dict)
            or existing.get("actor_id") != capability.actor_id
            or int(existing.get("fence") or 0) != int(fence)
        ):
            raise CollaborationConflict("workspace edit lease expired")
        return await self.acquire_lease(capability, normalized)

    async def release_lease(
        self, capability: WorkspaceCapability, path: str, fence: int | None = None
    ) -> bool:
        normalized = _safe_path(path)
        key = self._key(f"lease:{hashlib.sha256(normalized.encode()).hexdigest()}")
        existing = _decode(await _call(self.redis, "get", key), {})
        if not isinstance(existing, dict) or existing.get("actor_id") != capability.actor_id:
            return False
        if fence is not None and int(existing.get("fence") or 0) != int(fence):
            raise CollaborationConflict("workspace edit lease changed")
        await _call(self.redis, "delete", key)
        await self._publish("lease_released")
        return True

    async def list_leases(self) -> list[dict[str, Any]]:
        # SCAN is bounded: a workspace cannot legitimately accumulate unbounded active leases.
        cursor: Any = 0
        out: list[dict[str, Any]] = []
        for _ in range(4):
            result = await _call(
                self.redis, "scan", cursor=cursor, match=f"{self.prefix}:lease:*", count=32
            )
            if not isinstance(result, (tuple, list)) or len(result) != 2:
                break
            cursor, keys = result
            for key in keys or []:
                value = _decode(await _call(self.redis, "get", key), {})
                if isinstance(value, dict) and value.get("path"):
                    try:
                        lease = Lease(**value)
                        out.append(lease.public())
                    except (TypeError, ValueError):
                        continue
            if cursor in {0, "0", b"0"} or len(out) >= 64:
                break
        return sorted(out, key=lambda item: item["path"])

    async def list_issues(self, *, include_resolved: bool = False) -> list[dict[str, Any]]:
        raw = await self._get_json(self._key("issues"), [])
        issues: list[dict[str, Any]] = []
        for value in raw if isinstance(raw, list) else []:
            if not isinstance(value, dict):
                continue
            try:
                issue = WorkspaceIssue(**value)
            except (TypeError, ValueError):
                continue
            if include_resolved or issue.status != "resolved":
                issues.append(issue.public())
        return sorted(issues, key=lambda item: (item["status"] == "resolved", -item["updated_at"]))

    async def _save_issues(self, issues: list[dict[str, Any]]) -> None:
        await self._set_json(self._key("issues"), issues[:MAX_ISSUES])

    async def create_issue(
        self,
        capability: WorkspaceCapability,
        *,
        path: str,
        start_line: int,
        end_line: int,
        revision: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        if capability.role != ROLE_UI:
            raise CollaborationForbidden("only the workspace owner may create issues")
        normalized = _safe_path(path)
        if not (1 <= int(start_line) <= int(end_line) <= 1_000_000):
            raise CollaborationConflict("invalid issue range")
        clean_title = str(title or "").strip()[:MAX_ISSUE_TITLE]
        clean_body = str(body or "").strip()[:MAX_ISSUE_BODY]
        if not clean_title:
            raise CollaborationConflict("issue title is required")
        issues = await self.list_issues(include_resolved=True)
        if len(issues) >= MAX_ISSUES:
            raise CollaborationConflict("workspace issue limit reached")
        now = _now()
        issue = WorkspaceIssue(
            issue_id=secrets.token_urlsafe(12),
            path=normalized,
            start_line=int(start_line),
            end_line=int(end_line),
            revision=str(revision or "")[:64],
            title=clean_title,
            body=clean_body,
            status="open",
            created_at=now,
            updated_at=now,
        ).public()
        await self._save_issues([issue, *issues])
        await self._publish("issue_created")
        return issue

    async def update_issue(
        self,
        capability: WorkspaceCapability,
        issue_id: str,
        *,
        status: str | None = None,
        revision: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        if capability.role not in {ROLE_UI, ROLE_AGENT}:
            raise CollaborationForbidden("workspace actor required")
        issues = await self.list_issues(include_resolved=True)
        for index, issue in enumerate(issues):
            if hmac.compare_digest(str(issue.get("issue_id") or ""), str(issue_id)):
                new_status = str(status or issue["status"])
                if new_status not in {"open", "resolved", "stale"}:
                    raise CollaborationConflict("invalid issue status")
                start = int(start_line if start_line is not None else issue["start_line"])
                end = int(end_line if end_line is not None else issue["end_line"])
                if not (1 <= start <= end <= 1_000_000):
                    raise CollaborationConflict("invalid issue range")
                updated = {
                    **issue,
                    "status": new_status,
                    "start_line": start,
                    "end_line": end,
                    "revision": str(revision if revision is not None else issue["revision"])[:64],
                    "updated_at": _now(),
                }
                issues[index] = updated
                await self._save_issues(issues)
                await self._publish(
                    "issue_resolved" if new_status == "resolved" else "issue_updated"
                )
                return updated
        raise CollaborationConflict("workspace issue was not found")

    async def mark_stale(self, *, path: str, revision: str) -> int:
        normalized = _safe_path(path)
        issues = await self.list_issues(include_resolved=True)
        changed = 0
        for issue in issues:
            if (
                issue["path"] == normalized
                and issue["status"] == "open"
                and issue["revision"] != str(revision or "")
            ):
                issue["status"] = "stale"
                issue["updated_at"] = _now()
                changed += 1
        if changed:
            await self._save_issues(issues)
            await self._publish("issue_stale", count=changed)
        return changed

    async def preflight(
        self,
        capability: WorkspaceCapability,
        *,
        mutation: str,
        path: str = "",
        fence: int | None = None,
    ) -> dict[str, Any]:
        if mutation not in SAFE_MUTATIONS:
            raise CollaborationForbidden("unsupported workspace mutation")
        await self.initialize()
        if capability.role == ROLE_AGENT:
            await self.agent_safe_boundary(capability)
        normalized = _safe_path(path) if path else ""
        lease: Lease | None = None
        if normalized:
            lease = await self.acquire_lease(capability, normalized)
            if fence is not None and lease.fence != int(fence):
                raise CollaborationConflict("workspace edit lease changed")
        return {
            "allowed": True,
            "path": normalized,
            "fence": lease.fence if lease else 0,
            "state": "running",
        }


def signed_internal_request(
    method: str, path: str, body: bytes, timestamp: int | None = None
) -> dict[str, str]:
    """Headers for sidecar→backend calls; body is never logged by this module."""
    now = int(timestamp or _now())
    digest = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()}\n{path}\n{now}\n{digest}".encode()
    signature = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return {"X-Workspace-Timestamp": str(now), "X-Workspace-Signature": signature}


def verify_internal_request(
    method: str, path: str, body: bytes, timestamp: str, signature: str
) -> None:
    try:
        at = int(timestamp)
    except (TypeError, ValueError):
        raise CollaborationForbidden("invalid coordinator signature") from None
    if abs(_now() - at) > 60:
        raise CollaborationForbidden("expired coordinator signature")
    expected = signed_internal_request(method, path, body, timestamp=at)["X-Workspace-Signature"]
    if not hmac.compare_digest(str(signature or ""), expected):
        raise CollaborationForbidden("invalid coordinator signature")
