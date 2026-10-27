"""Private ledger checkpoint frames, separate from AgentEvent and public trace."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from service.domain.execution.context import observe_run_usage
from service.domain.usage.ledger import UsageLedger
from service.presentation.routers.agent.usage_checkpoint import checkpoint_observer

RESULT_KEY = "__audit_result__"


async def stream_audit_usage(
    attempt: str, execute: Callable[[], Awaitable[dict[str, Any]]]
) -> AsyncIterator[bytes]:
    """Coalesce full snapshots; never drop a receipt or expose provider payloads.

    Consumer must commit each checkpoint before acknowledging a result. This is
    not a durable producer journal: disconnect during a call remains uncertain.
    """
    changed = asyncio.Event()
    pending: tuple[str, object] | None = None
    subscriptions: list[Callable[[], None]] = []

    def emit(key: str, value: object) -> None:
        nonlocal pending
        pending = (key, value)
        changed.set()

    def bind(ledger: UsageLedger) -> None:
        subscriptions.append(ledger.subscribe(checkpoint_observer(attempt, emit)))

    async def run() -> dict[str, Any]:
        with observe_run_usage(bind):
            return await execute()

    task = asyncio.create_task(run())
    task.add_done_callback(lambda _: changed.set())
    try:
        while True:
            await changed.wait()
            changed.clear()
            if pending is not None:
                key, value = pending
                pending = None
                yield _frame(key, value)
            if task.done():
                try:
                    result = task.result()
                except Exception:
                    result = {"status": "internal", "passed": False, "retryable": True}
                yield _frame(RESULT_KEY, result)
                return
    finally:
        if not task.done():
            task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (Exception, asyncio.CancelledError):
            pass
        for unsubscribe in subscriptions:
            unsubscribe()


def _frame(key: str, value: object) -> bytes:
    return (json.dumps({key: value}, ensure_ascii=False, default=lambda _: None) + "\n").encode()
