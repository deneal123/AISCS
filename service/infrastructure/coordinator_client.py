"""Narrow client for the backend-owned workspace collaboration coordinator.

The workspace sidecar stays off the internal Redis network.  Before a mutable
operation it asks the backend for a signed, bounded decision.  No command,
file content, URL, owner id, or model data is sent to this API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx


class CoordinationError(Exception):
    code = "workspace_unavailable"


class CoordinationConflict(CoordinationError):
    code = "workspace_conflict"


class CoordinationPaused(CoordinationError):
    code = "workspace_paused"


class CoordinationCancelled(CoordinationError):
    code = "workspace_cancelled"


class CoordinationForbidden(CoordinationError):
    code = "workspace_forbidden"


@dataclass(frozen=True, slots=True)
class CoordinationDecision:
    allowed: bool
    path: str = ""
    fence: int = 0
    state: str = "running"


def _config() -> tuple[str, bytes, float]:
    base = str(os.environ.get("WORKSPACE_COORDINATOR_URL") or "").rstrip("/")
    secret = str(os.environ.get("WORKSPACE_COORDINATION_SECRET") or "")
    timeout = min(10.0, max(0.2, float(os.environ.get("WORKSPACE_COORDINATOR_TIMEOUT_SEC") or 2.0)))
    if not base or not secret:
        raise CoordinationError("workspace coordination is not configured")
    return base, secret.encode("utf-8"), timeout


def _headers(
    method: str, path: str, body: bytes, secret: bytes, correlation_id: str = ""
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()}\n{path}\n{timestamp}\n{digest}".encode()
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Workspace-Timestamp": timestamp,
        "X-Workspace-Signature": signature,
        "X-Correlation-Id": correlation_id or uuid.uuid4().hex,
    }


def _raise(status: int, payload: Any) -> None:
    code = ""
    if isinstance(payload, dict):
        detail = payload.get("detail")
        code = str(detail.get("code") or "") if isinstance(detail, dict) else ""
    if code == "workspace_conflict" or status == 409:
        raise CoordinationConflict("workspace coordination conflict")
    if code == "workspace_paused" or status == 423:
        raise CoordinationPaused("workspace run is paused")
    if code == "workspace_cancelled":
        raise CoordinationCancelled("workspace run is cancelled")
    if status in {401, 403}:
        raise CoordinationForbidden("workspace coordination denied")
    raise CoordinationError("workspace coordination is unavailable")


async def _request(
    path: str, payload: dict[str, Any], *, correlation_id: str = ""
) -> dict[str, Any]:
    base, secret, timeout = _config()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base}{path}",
                content=raw,
                headers=_headers("POST", path, raw, secret, correlation_id),
            )
    except (httpx.TimeoutException, httpx.TransportError):
        raise CoordinationError("workspace coordination is unavailable") from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400:
        _raise(response.status_code, data)
    if not isinstance(data, dict):
        raise CoordinationError("workspace coordinator returned invalid response")
    return data


async def preflight(
    capability: str,
    mutation: str,
    *,
    path: str = "",
    workspace_id: str = "",
    fence: int | None = None,
    correlation_id: str = "",
) -> CoordinationDecision:
    payload: dict[str, Any] = {
        "capability": str(capability),
        "mutation": str(mutation),
        "path": str(path),
        "workspace_id": str(workspace_id),
    }
    if fence is not None:
        payload["fence"] = int(fence)
    data = await _request(
        "/internal/workspace-coordination/preflight", payload, correlation_id=correlation_id
    )
    if not bool(data.get("allowed")):
        raise CoordinationForbidden("workspace mutation was not allowed")
    return CoordinationDecision(
        allowed=True,
        path=str(data.get("path") or ""),
        fence=int(data.get("fence") or 0),
        state=str(data.get("state") or "running"),
    )


async def release_ide_lease(capability: str, *, workspace_id: str, path: str, fence: int) -> bool:
    data = await _request(
        "/internal/workspace-coordination/ide/release",
        {
            "capability": capability,
            "workspace_id": workspace_id,
            "path": path,
            "fence": fence,
        },
    )
    if not isinstance(data.get("released"), bool):
        raise CoordinationError("invalid lease release acknowledgement")
    return data["released"]


async def safe_boundary(capability: str, *, correlation_id: str = "") -> str:
    data = await _request(
        "/internal/workspace-coordination/boundary",
        {"capability": str(capability)},
        correlation_id=correlation_id,
    )
    state = data.get("state")
    return str((state or {}).get("state") or "running") if isinstance(state, dict) else "running"


async def list_issues(capability: str, *, correlation_id: str = "") -> list[dict[str, Any]]:
    data = await _request(
        "/internal/workspace-coordination/issues",
        {"capability": str(capability)},
        correlation_id=correlation_id,
    )
    issues = data.get("issues")
    return [item for item in issues if isinstance(item, dict)] if isinstance(issues, list) else []


async def update_issue(
    capability: str,
    issue_id: str,
    *,
    status: str | None = None,
    revision: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"capability": str(capability), "issue_id": str(issue_id)}
    if status is not None:
        payload["status"] = str(status)
    if revision is not None:
        payload["revision"] = str(revision)
    data = await _request("/internal/workspace-coordination/issues/update", payload)
    return data.get("issue") if isinstance(data.get("issue"), dict) else {}
