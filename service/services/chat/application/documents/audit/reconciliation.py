"""Resolve started audit accounting before artifact status can bypass settlement."""

from collections.abc import Awaitable, Callable
from typing import Any

from service.services.chat.application.documents.audit.recovery import recover_started_result
from service.services.chat.persistence.documents.audit.attempts import started_id


async def reconcile_started_audit(
    config: Any,
    pg_connector: Any,
    redis: Any,
    session: Any,
    row: dict,
    settle_pending: Callable[..., Awaitable[None]],
) -> bool:
    attempt = await started_id(session, row)
    if attempt is None:
        return True
    recorded = await recover_started_result(
        config=config,
        session=session,
        row=row,
        ref={"user_id": str(row["user_id"]), "workspace_id": str(row["workspace_id"])},
        attempt_id=attempt,
    )
    if recorded is None:
        # Another consumer may have sealed/settled under the same row lock.
        # A surviving started attempt is still unresolved, regardless of age.
        if await started_id(session, row) is not None:
            return False
    await settle_pending(
        config=config, pg_connector=pg_connector, redis=redis, session=session, row=row
    )
    return True
