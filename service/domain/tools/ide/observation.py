"""Bounded observation of one command, including an uncertain dispatch ACK."""

import asyncio

from service.shared.harness_protocol import HarnessFailure

OBSERVABLE = frozenset({"preparing", "ready", "dispatching", "running", "stopping", "unknown"})


async def observe_command(execution, client, operation_id, data):
    deadline = getattr(execution, "run_deadline", None)
    timeout = max(0, deadline.clamp(130)) if deadline else 130
    try:
        async with asyncio.timeout(timeout):
            while data["state"] in OBSERVABLE:
                if execution.cancelled:
                    return await client.command(action="stop", operation_id=operation_id)
                await asyncio.sleep(0.5)
                try:
                    data = await client.command(action="status", operation_id=operation_id)
                except HarnessFailure as error:
                    if error.code != "checkpoint_unavailable":
                        raise
                    # Observation can be retried; GO and other effects cannot.
    except TimeoutError:
        # An unobserved result stays unknown/blocked. It is not a fresh execute
        # permission, a successful check or evidence of process cleanup.
        pass
    return data
