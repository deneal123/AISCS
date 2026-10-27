"""Bounded observation/Stop after restart. This loop never creates or dispatches."""

import asyncio
from uuid import UUID

from service.services.chat.application.harness_capability import issue
from service.services.chat.persistence.harness.commands.recovery import candidates


async def command_reconciliation(infra):
    from service.composition.ide_commands import build_agent_console

    cursor = None
    while True:
        try:
            rows = await candidates(infra.pg_connector, cursor)
            service = build_agent_console(infra)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient DB failure must not permanently retire observation.
            # Nothing is dispatched and no uncertain gate is released here.
            await asyncio.sleep(2)
            continue
        for owner, operation_id, stop in rows:
            try:
                await service.status(owner, operation_id, issue(owner), stop=stop)
            except Exception:
                # No inferred completion, effect replay or removal of an unknown
                # gate. A transient status read is safe to revisit next sweep.
                pass
            cursor = (UUID(owner.task_id), operation_id)
        if not rows:
            cursor = None
        await asyncio.sleep(2)
