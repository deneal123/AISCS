"""Private, bounded persistence contract for a prepared worker result.

This envelope is not an AgentEvent, assistant metadata, or a provider response.
Only the owning worker transaction may write it. Runtime resume wiring must
use the decoded projection, never deserialize arbitrary execution context.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from service.models.key_value import ProcessingStatus
from service.services.chat.domain.chat_exceptions import JobServiceUnavailableError

CHECKPOINT_KEY = "_prepared_turn_v1"
ACCEPTED_KEY = "_accepted_turn_v1"
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024
_PRIVATE_KEYS = frozenset(
    {
        "capability",
        "coordination_capability",
        "workspace_token",
        "authorization",
        "credentials",
        "api_key",
        "access_token",
        "refresh_token",
        "functions_state_id",
        "b64_json",
        "pptx_b64",
        "_pending_artifacts",
        "raw_response",
        "provider_response",
        "file_key",
        "storage_key",
        "presigned_url",
        "file_url",
        "engine_env",
        "workspace_ref",
        "provider_state",
        "headers",
        "artifact_bytes",
        "original_error",
        "error_detail",
    }
)
_PRIVATE_KEYS_CANONICAL = frozenset(re.sub(r"[^a-z0-9]", "", key) for key in _PRIVATE_KEYS)


class PreparedCheckpointInvalid(JobServiceUnavailableError):
    """An unsafe or unbound result must not become a durable recovery latch."""


def _invalid() -> PreparedCheckpointInvalid:
    return PreparedCheckpointInvalid("Prepared result unavailable")


def _validate_tree(value: Any, depth: int = 0) -> None:
    if depth > 16:
        raise _invalid()
    if type(value) is str and len(value) > MAX_CHECKPOINT_BYTES:
        raise _invalid()
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        if len(value) > 4096:
            raise _invalid()
        for item in value:
            _validate_tree(item, depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 256:
            raise _invalid()
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or re.sub(r"[^a-z0-9]", "", key.lower()) in _PRIVATE_KEYS_CANONICAL
            ):
                raise _invalid()
            _validate_tree(item, depth + 1)
        return
    # Do not fall back to str(value): object representations can contain secrets.
    raise _invalid()


def _encode(body: dict[str, Any]) -> bytes:
    _validate_tree(body)
    try:
        encoded = json.dumps(
            body, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise _invalid() from None
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise _invalid()
    return encoded


@dataclass(frozen=True, slots=True, repr=False)
class PreparedTurnCheckpoint:
    """An immutable canonical value, not a shared mutable metadata dictionary."""

    _body: bytes
    digest: str

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        owner_id: str,
        thread_id: str,
        reply: str,
        model: str | None,
        metadata: dict[str, Any],
        usage: dict[str, Any],
    ) -> PreparedTurnCheckpoint:
        try:
            job, owner = str(UUID(job_id)), str(UUID(owner_id))
        except (ValueError, TypeError, AttributeError):
            raise _invalid() from None
        if (
            not isinstance(thread_id, str)
            or not 0 < len(thread_id) <= 128
            or not isinstance(reply, str)
            or not isinstance(metadata, dict)
            or not isinstance(usage, dict)
            or (model is not None and (not isinstance(model, str) or not 0 < len(model) <= 160))
        ):
            raise _invalid()
        body = {
            "version": 1,
            "job_id": job,
            "owner_id": owner,
            "thread_id": thread_id,
            "reply": reply,
            "model": model,
            "metadata": metadata,
            "usage": usage,
        }
        encoded = _encode(body)
        return cls(encoded, hashlib.sha256(encoded).hexdigest())

    def payload(self) -> dict[str, Any]:
        # Returning a fresh copy prevents callers from changing the accepted value.
        return {"body": json.loads(self._body), "sha256": self.digest}

    @classmethod
    def decode(
        cls, envelope: Any, *, job_id: str, owner_id: str, thread_id: str
    ) -> PreparedTurnCheckpoint:
        if not isinstance(envelope, dict) or set(envelope) != {"body", "sha256"}:
            raise _invalid()
        body = envelope["body"]
        fields = {
            "version",
            "job_id",
            "owner_id",
            "thread_id",
            "reply",
            "model",
            "metadata",
            "usage",
        }
        if not isinstance(body, dict) or set(body) != fields or type(body["version"]) is not int:
            raise _invalid()
        if body["version"] != 1:
            raise _invalid()
        checkpoint = cls.create(**{key: body[key] for key in fields if key != "version"})
        if (
            checkpoint.digest != envelope["sha256"]
            or body["job_id"] != job_id
            or body["owner_id"] != owner_id
            or body["thread_id"] != thread_id
        ):
            raise _invalid()
        return checkpoint


async def store_prepared_turn(
    repository: Any, session: Any, checkpoint: PreparedTurnCheckpoint
) -> bool:
    """Stage a checkpoint without committing the caller's transaction.

    A same-digest replay is a no-op. Different prepared results never silently
    overwrite one another, nor overwrite an already terminal job.
    """
    try:
        if not isinstance(checkpoint._body, bytes) or len(checkpoint._body) > MAX_CHECKPOINT_BYTES:
            raise _invalid()
        body = checkpoint.payload()["body"]
        # Defend this persistence boundary even against manually constructed
        # dataclass instances, not just instances returned by create().
        checkpoint = PreparedTurnCheckpoint.decode(
            checkpoint.payload(),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        from service.services.chat.infrastructure.chat_worker.billing.accepted_accounting import (
            lock_acceptance_accounting,
        )

        payload = await lock_acceptance_accounting(repository, session, body)
        if ACCEPTED_KEY in payload:
            # Direct compatibility capture must enforce the same codec and
            # first-winner facts as the explicit accepted promotion path.
            from service.services.chat.infrastructure.chat_worker.results.accepted import (
                decode_accepted,
            )

            accepted = decode_accepted(
                payload[ACCEPTED_KEY],
                job_id=body["job_id"],
                owner_id=body["owner_id"],
                thread_id=body["thread_id"],
            ).payload()["body"]
            if any(accepted[key] != body[key] for key in ("reply", "model", "usage")):
                raise _invalid()
        staged = await repository.stage_prepared_turn(
            UUID(body["job_id"]),
            UUID(body["owner_id"]),
            body["thread_id"],
            json.dumps(checkpoint.payload(), ensure_ascii=False, separators=(",", ":")),
            session=session,
        )
        if staged:
            return True
        job = await repository.fetch_job_by_id(
            UUID(body["job_id"]), UUID(body["owner_id"]), session=session
        )
        if job is None or job.status != ProcessingStatus.PROCESSING:
            raise _invalid()
        payload = job.payload if isinstance(job.payload, dict) else {}
        if payload.get("thread_id") != body["thread_id"]:
            raise _invalid()
        previous = payload.get(CHECKPOINT_KEY)
        accepted = PreparedTurnCheckpoint.decode(
            previous,
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        if accepted.digest != checkpoint.digest:
            raise _invalid()
        return False
    except PreparedCheckpointInvalid:
        raise
    except Exception:
        raise _invalid() from None
