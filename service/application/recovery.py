"""Signed, privacy-safe metadata used to recover workspace containers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from domain.ownership import _secret
from domain.policy import WorkspacePolicy

LABEL_MANAGED = "gpthub.workspace"
LABEL_MANIFEST = "gpthub.workspace.manifest.v2"
MANIFEST_VERSION = 2
_DOMAIN = b"gpthub-workspace-manifest-v2|"


@dataclass(frozen=True, slots=True)
class RecoveryManifest:
    workspace_id: str
    expires_at: float
    owner_binding: str
    policy: WorkspacePolicy


def owner_binding(workspace_id: str, user_id: str) -> str:
    value = f"{workspace_id}|{user_id}".encode()
    return hmac.new(_secret().encode(), b"workspace-owner-v2|" + value, hashlib.sha256).hexdigest()


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def mint_manifest(
    workspace_id: str, user_id: str, expires_at: float, policy: WorkspacePolicy
) -> str:
    payload = {
        "v": MANIFEST_VERSION,
        "workspace_id": str(workspace_id),
        "expires_at": int(expires_at),
        "owner_binding": owner_binding(str(workspace_id), str(user_id)),
        "policy": policy.as_dict(),
    }
    raw = _canonical(payload)
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(_secret().encode(), _DOMAIN + raw, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def parse_manifest(value: str | None) -> RecoveryManifest | None:
    encoded, separator, signature = str(value or "").partition(".")
    if not separator or not encoded or not signature:
        return None
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        expected = hmac.new(_secret().encode(), _DOMAIN + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        payload = json.loads(raw)
        if set(payload) != {"v", "workspace_id", "expires_at", "owner_binding", "policy"}:
            return None
        if payload["v"] != MANIFEST_VERSION or not isinstance(payload["workspace_id"], str):
            return None
        if not isinstance(payload["owner_binding"], str) or len(payload["owner_binding"]) != 64:
            return None
        return RecoveryManifest(
            workspace_id=payload["workspace_id"],
            expires_at=float(payload["expires_at"]),
            owner_binding=payload["owner_binding"],
            policy=WorkspacePolicy(**payload["policy"]),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
