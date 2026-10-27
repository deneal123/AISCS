"""Private, immutable materialization facts; no binary payload or credentials.

Registered document artifacts can be delivered by the existing outbox. Owned
Library references can be rebound by FileService. In-memory legacy assets are
explicitly unresolved, never silently presented as recovered downloads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    ACCEPTED_KEY,
    CHECKPOINT_KEY,
    PreparedCheckpointInvalid,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import (
    _validate_recovery_fields,
)

_FIELDS = frozenset(
    {
        "version",
        "reservation_id",
        "reserved_estimate",
        "workspace_id",
        "expires_at",
        "publications",
        "pricing",
        "elapsed_seconds",
        "library_files",
        "unresolved_assets",
    }
)
_PUBLICATION_FIELDS = frozenset(
    {
        "build_id",
        "artifact_id",
        "role",
        "source_digest",
        "artifact_sha256",
        "artifact_size",
        "filename",
        "mime_type",
        "initial_status",
    }
)
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MIME = {"pdf": "application/pdf", "source_bundle": "application/zip"}
# Private JSON field identifier, not a credential.
MATERIALIZATION_KEY = "_materialization_plan_v1"  # gitleaks:allow


def _invalid() -> PreparedCheckpointInvalid:
    return PreparedCheckpointInvalid("Materialization unavailable")


def _filename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 1000
        and value not in {".", ".."}
        and not any(ch in value for ch in ("/", "\\", ":"))
        and all(ord(ch) >= 32 and ord(ch) != 127 for ch in value)
    )


def _validate(raw: Any) -> None:
    if not isinstance(raw, dict) or raw.get("version") not in (1, 2, 3):
        raise _invalid()
    expected = _FIELDS | {"context"} if raw["version"] >= 2 else _FIELDS
    if raw["version"] == 3:
        expected = expected | {"workspace_files"}
        from service.services.chat.infrastructure.chat_worker.materialization.workspace import (
            validated_inventory,
        )

        validated_inventory(raw.get("workspace_files"))
        if raw["workspace_files"] and not raw.get("workspace_id"):
            raise _invalid()
    if set(raw) != expected:
        raise _invalid()
    if raw["version"] >= 2:
        from service.services.chat.infrastructure.chat_worker.materialization.context import (
            validate_context,
        )

        validate_context(raw["context"], raw["library_files"])
    if type(raw["version"]) is not int or type(raw["unresolved_assets"]) is not int:
        raise _invalid()
    if not 0 <= raw["unresolved_assets"] <= 32:
        raise _invalid()
    private = {
        key: raw[key]
        for key in (
            "reservation_id",
            "reserved_estimate",
            "workspace_id",
            "expires_at",
            "publications",
            "pricing",
            "elapsed_seconds",
        )
    }
    private["primary_file_id"] = None
    _validate_recovery_fields({}, private)
    for item in raw["publications"]:
        if not isinstance(item, dict) or set(item) != _PUBLICATION_FIELDS:
            raise _invalid()
        if (
            item["role"] not in _MIME
            or item["mime_type"] != _MIME[item["role"]]
            or item["initial_status"] not in {"pending_audit", "pending_delivery"}
            or not _filename(item["filename"])
            or type(item["artifact_size"]) is not int
            or not 0 < item["artifact_size"] <= 64 * 1024 * 1024
        ):
            raise _invalid()
        for field in ("build_id", "artifact_id"):
            if not isinstance(item[field], str) or not _OPAQUE.fullmatch(item[field]):
                raise _invalid()
        for field in ("source_digest", "artifact_sha256"):
            if not isinstance(item[field], str) or not _DIGEST.fullmatch(item[field]):
                raise _invalid()
    files = raw["library_files"]
    if not isinstance(files, list) or len(files) > 32:
        raise _invalid()
    seen = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"file_id", "filename", "mime_type", "kind"}:
            raise _invalid()
        identity = str(UUID(item["file_id"]))
        if identity != item["file_id"] or identity in seen or not _filename(item["filename"]):
            raise _invalid()
        seen.add(identity)
        if item["kind"] not in {"file", "image", "presentation", "pdf", "source_bundle"}:
            raise _invalid()
        if not isinstance(item["mime_type"], str) or not re.fullmatch(
            r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", item["mime_type"]
        ):
            raise _invalid()
    identities = [
        (item["build_id"], item["artifact_id"], item["role"]) for item in raw["publications"]
    ]
    if len(set(identities)) != len(identities):
        raise _invalid()


@dataclass(frozen=True, slots=True, repr=False)
class MaterializationPlan:
    _body: bytes

    @classmethod
    def from_payload(cls, raw: Any) -> MaterializationPlan:
        try:
            _validate(raw)
            body = json.dumps(
                raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
            ).encode()
            if len(body) > 128 * 1024:
                raise _invalid()
            return cls(body)
        except Exception:
            raise _invalid() from None

    def payload(self) -> dict[str, Any]:
        # Defend manually constructed instances and return a fresh projection.
        try:
            if not isinstance(self._body, bytes) or len(self._body) > 128 * 1024:
                raise _invalid()
            raw = json.loads(self._body)
            _validate(raw)
            return raw
        except Exception:
            raise _invalid() from None

    def validate_promotion(self, prepared_metadata: Any) -> None:
        raw = self.payload()
        private = prepared_metadata.get("private") if isinstance(prepared_metadata, dict) else None
        if not isinstance(private, dict) or any(
            private.get(key) != raw[key]
            for key in (
                "reservation_id",
                "reserved_estimate",
                "workspace_id",
                "expires_at",
                "publications",
                "pricing",
            )
        ):
            raise _invalid()


async def stage_materialization(repository: Any, session: Any, accepted: Any, plan: Any) -> bool:
    """Stage both first-winner facts atomically; caller owns commit/recovery lock."""
    from service.models.key_value import ProcessingStatus
    from service.services.chat.infrastructure.chat_worker.billing.accepted_accounting import (
        lock_acceptance_accounting,
    )
    from service.services.chat.infrastructure.chat_worker.results.accepted import decode_accepted

    try:
        body = accepted.payload()["body"]
        checked = decode_accepted(
            accepted.payload(),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        materialization = MaterializationPlan.from_payload(plan.payload()).payload()
        envelope = {ACCEPTED_KEY: checked.payload(), MATERIALIZATION_KEY: materialization}
        owner, job_id = UUID(body["owner_id"]), UUID(body["job_id"])
        await lock_acceptance_accounting(repository, session, body)
        if await repository.stage_accepted_materialization(
            job_id, owner, body["thread_id"], json.dumps(envelope, allow_nan=False), session=session
        ):
            return True
        row = await repository.lock_prepared_turn(job_id, owner, session=session)
        if (
            row is None
            or row["status"] != ProcessingStatus.PROCESSING
            or row["payload"].get("thread_id") != body["thread_id"]
            or CHECKPOINT_KEY in row["payload"]
            or any(row["payload"].get(key) != value for key, value in envelope.items())
        ):
            raise _invalid()
        return False
    except Exception:
        raise _invalid() from None


async def recover_materialization(
    plan: MaterializationPlan, *, owner_id: str, file_service: Any
) -> dict[str, Any]:
    """Owner-check references; never invoke a provider, upload or charge."""
    try:
        raw = plan.payload()
        # A durable reference is not a reconstruction of a lost binary buffer.
        if raw["unresolved_assets"]:
            raise JobStateUnavailable("Materialization unavailable")
        owner = UUID(owner_id)
        for item in raw["library_files"]:
            owned = await file_service.fetch_file_metadata(owner, UUID(item["file_id"]))
            if owned is None or str(owned.file_id) != item["file_id"]:
                raise JobStateUnavailable("Materialization unavailable")
        return {
            "metadata": {
                **raw.get("context", {}).get("metadata", {}),
                "generated_files": raw["library_files"],
                "_document_publications": raw["publications"],
            },
            "workspace_ref": {"workspace_id": raw["workspace_id"], "expires_at": raw["expires_at"]}
            if raw["workspace_id"]
            else None,
            "reservation_id": raw["reservation_id"],
            "reserved_estimate": raw["reserved_estimate"],
            "pricing": raw["pricing"],
            "elapsed_seconds": raw["elapsed_seconds"],
            "catalog": {
                "observations": raw.get("context", {}).get("observations", []),
                "executions": raw.get("context", {}).get("executions", []),
            },
        }
    except Exception:
        raise JobStateUnavailable("Materialization unavailable") from None
