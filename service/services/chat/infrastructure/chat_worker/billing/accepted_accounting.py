"""Bind first-winner result accounting inside the owned settlement transaction."""

from typing import Any
from uuid import UUID

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
    require_stored_usage,
)


async def lock_acceptance_accounting(repository: Any, session: Any, body: dict) -> dict[str, Any]:
    """Caller retains the row lock through accepted admission and commit.

    A process-local journal snapshot can lag a committed checkpoint. Check the
    canonical row before writing any accepted facts; no provider, charge or
    compensation belongs here. Legacy rows without a journal remain compatible.
    """
    row = await repository.lock_prepared_turn(
        UUID(body["job_id"]), UUID(body["owner_id"]), session=session
    )
    if (
        row is None
        or row["status"] != ProcessingStatus.PROCESSING
        or not isinstance(row.get("payload"), dict)
        or row["payload"].get("thread_id") != body["thread_id"]
    ):
        raise ValueError("Accepted accounting unavailable")
    require_stored_usage(body["usage"], row["payload"])
    return row["payload"]
