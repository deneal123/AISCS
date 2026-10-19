"""Signed, privacy-safe metadata used to recover workspace containers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Any

from domain.ownership import _secret
from domain.policy import WorkspacePolicy

LABEL_MANAGED = "gpthub.workspace"
LABEL_MANIFEST = "gpthub.workspace.manifest.v2"
MANIFEST_VERSION = 2
_DOMAIN = b"gpthub-workspace-manifest-v2|"
_RESTORE_DOMAIN = b"gpthub-workspace-manifest-v3|"


@dataclass(frozen=True, slots=True)
class RestoreSnapshot:
    """Private selected immutable capsule identity, not arbitrary source bytes."""

    sha256: str = field(repr=False)
    size: int

    def __post_init__(self) -> None:
        if (
            type(self.sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", self.sha256)
            or type(self.size) is not int
            or not 0 < self.size < 2**31
        ):
            raise ValueError("invalid_restore_snapshot")


@dataclass(frozen=True, slots=True)
class RecoveryManifest:
    workspace_id: str
    expires_at: float
    owner_binding: str
    policy: WorkspacePolicy
    restore_snapshot: RestoreSnapshot | None = field(default=None, repr=False)


def owner_binding(workspace_id: str, user_id: str) -> str:
    value = f"{workspace_id}|{user_id}".encode()
    return hmac.new(_secret().encode(), b"workspace-owner-v2|" + value, hashlib.sha256).hexdigest()


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def mint_manifest(
    workspace_id: str,
    user_id: str,
    expires_at: float,
    policy: WorkspacePolicy,
    *,
    restore_snapshot: RestoreSnapshot | None = None,
) -> str:
    payload = {
        "v": 3 if restore_snapshot else MANIFEST_VERSION,
        "workspace_id": str(workspace_id),
        "expires_at": int(expires_at),
        "owner_binding": owner_binding(str(workspace_id), str(user_id)),
        "policy": policy.as_dict(),
    }
    if restore_snapshot is not None:
        payload["restore"] = {"sha256": restore_snapshot.sha256, "size": restore_snapshot.size}
    raw = _canonical(payload)
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    domain = _RESTORE_DOMAIN if restore_snapshot else _DOMAIN
    signature = hmac.new(_secret().encode(), domain + raw, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def parse_manifest(value: str | None) -> RecoveryManifest | None:
    encoded, separator, signature = str(value or "").partition(".")
    if not separator or not encoded or not signature:
        return None
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(raw)
        if type(payload) is not dict:
            return None
        version = payload.get("v")
        domain = _RESTORE_DOMAIN if version == 3 else _DOMAIN
        expected = hmac.new(_secret().encode(), domain + raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        fields = {"v", "workspace_id", "expires_at", "owner_binding", "policy"}
        if version == 3:
            fields.add("restore")
        if set(payload) != fields:
            return None
        if (
            type(version) is not int
            or version not in {MANIFEST_VERSION, 3}
            or not isinstance(payload["workspace_id"], str)
        ):
            return None
        if not isinstance(payload["owner_binding"], str) or len(payload["owner_binding"]) != 64:
            return None
        return RecoveryManifest(
            workspace_id=payload["workspace_id"],
            expires_at=float(payload["expires_at"]),
            owner_binding=payload["owner_binding"],
            policy=WorkspacePolicy(**payload["policy"]),
            restore_snapshot=RestoreSnapshot(**payload["restore"]) if version == 3 else None,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def restore_receipt(manifest: str) -> str:
    """A sandbox cannot mint completion from the visible signed creation label."""
    parsed = parse_manifest(manifest)
    if parsed is None or parsed.restore_snapshot is None:
        raise ValueError("invalid_restore_manifest")
    return hmac.new(
        _secret().encode(), b"gpthub-ide-restore-ready-v1|" + manifest.encode(), hashlib.sha256
    ).hexdigest()
