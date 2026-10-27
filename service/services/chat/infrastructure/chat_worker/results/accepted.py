"""Private first-winner reply/usage latch; never an artifact persistence envelope.

This seam stages only accepted model facts. It intentionally has no commit,
charging, provider invocation or automatic promotion to a prepared result.
The worker owns commit and the subsequent materialization transition.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.accepted_accounting import (
    lock_acceptance_accounting,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    ACCEPTED_KEY,
    CHECKPOINT_KEY,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
    store_prepared_turn,
)
from service.services.chat.infrastructure.chat_worker.results.prepared import _validate_usage

_SAFE_PROVENANCE = re.compile(r"[A-Za-z0-9_.:/-]{1,160}")


def _provenance(model: str | None, usage: dict[str, Any]) -> None:
    values = [model] if model is not None else []
    for call in usage.get("per_call_usage", []):
        values.extend(
            call[key]
            for key in ("provider", "model", "call_id", "receipt_id")
            if call.get(key) is not None
        )
    if any(
        not isinstance(value, str) or "://" in value or not _SAFE_PROVENANCE.fullmatch(value)
        for value in values
    ):
        raise PreparedCheckpointInvalid("Accepted result unavailable")


def accepted_turn(
    *,
    job_id: str,
    owner_id: str,
    thread_id: str,
    reply: str,
    model: str | None,
    usage: dict[str, Any],
) -> PreparedTurnCheckpoint:
    """Reuse the bounded canonical codec without accepting artifact metadata."""
    _validate_usage(usage)
    _provenance(model, usage)
    return PreparedTurnCheckpoint.create(
        job_id=job_id,
        owner_id=owner_id,
        thread_id=thread_id,
        reply=reply,
        model=model,
        metadata={},
        usage=usage,
    )


def decode_accepted(
    envelope: Any, *, job_id: str, owner_id: str, thread_id: str
) -> PreparedTurnCheckpoint:
    checkpoint = PreparedTurnCheckpoint.decode(
        envelope, job_id=job_id, owner_id=owner_id, thread_id=thread_id
    )
    body = checkpoint.payload()["body"]
    if body["metadata"]:
        raise PreparedCheckpointInvalid("Accepted result unavailable")
    _validate_usage(body["usage"])
    _provenance(body["model"], body["usage"])
    return checkpoint


async def stage_accepted(repository: Any, session: Any, checkpoint: PreparedTurnCheckpoint) -> bool:
    """Stage exactly one owned accepted value, or verify a same-digest replay."""
    try:
        body = checkpoint.payload()["body"]
        checkpoint = decode_accepted(
            checkpoint.payload(),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        job_id, owner_id = UUID(body["job_id"]), UUID(body["owner_id"])
        await lock_acceptance_accounting(repository, session, body)
        if await repository.stage_accepted_turn(
            job_id,
            owner_id,
            body["thread_id"],
            json.dumps(checkpoint.payload(), ensure_ascii=False, separators=(",", ":")),
            session=session,
        ):
            return True
        job = await repository.fetch_job_by_id(job_id, owner_id, session=session)
        if job is None or job.status != ProcessingStatus.PROCESSING:
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        payload = job.payload if isinstance(job.payload, dict) else {}
        if payload.get("thread_id") != body["thread_id"] or CHECKPOINT_KEY in payload:
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        previous = decode_accepted(
            payload.get(ACCEPTED_KEY),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        if previous.digest != checkpoint.digest:
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        return False
    except Exception:
        raise PreparedCheckpointInvalid("Accepted result unavailable") from None


async def promote_accepted(repository: Any, session: Any, prepared: PreparedTurnCheckpoint) -> bool:
    """Promote under the owned row lock without changing accepted model facts."""
    try:
        body = prepared.payload()["body"]
        prepared = PreparedTurnCheckpoint.decode(
            prepared.payload(),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        )
        job = await repository.lock_prepared_turn(
            UUID(body["job_id"]), UUID(body["owner_id"]), session=session
        )
        if job is None or job["status"] != ProcessingStatus.PROCESSING:
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        payload = job["payload"] if isinstance(job["payload"], dict) else {}
        if payload.get("thread_id") != body["thread_id"]:
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        accepted = decode_accepted(
            payload.get(ACCEPTED_KEY),
            job_id=body["job_id"],
            owner_id=body["owner_id"],
            thread_id=body["thread_id"],
        ).payload()["body"]
        if any(accepted[key] != body[key] for key in ("reply", "model", "usage")):
            raise PreparedCheckpointInvalid("Accepted result unavailable")
        return await store_prepared_turn(repository, session, prepared)
    except Exception:
        raise PreparedCheckpointInvalid("Accepted result unavailable") from None
