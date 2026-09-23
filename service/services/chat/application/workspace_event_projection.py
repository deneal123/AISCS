"""Safe projection of workspace-room invalidations into a chat stream."""

from __future__ import annotations

import json
from typing import Any

from service.infrastructure.messaging import stream_helpers

SAFE_ACTIONS = frozenset(
    {
        "lease_acquired",
        "lease_released",
        "file_saved",
        "library_copied",
        "library_changed",
        "issue_created",
        "issue_updated",
        "issue_resolved",
        "issue_stale",
        "agent_started",
        "agent_waiting",
        "agent_paused",
        "agent_resumed",
        "agent_cancelled",
        "workspace_recovered",
    }
)


async def publish_workspace_invalidation(
    redis: Any,
    *,
    thread_id: str,
    action: str,
    state: str = "running",
    revision_changed: bool = False,
) -> None:
    """Publish no content: clients re-fetch workspace data through REST."""

    if not redis or not thread_id or action not in SAFE_ACTIONS:
        return
    safe_state = state if state in {"running", "paused", "cancelled", "unavailable"} else "running"
    payload = {
        "type": "status_update",
        "metadata": {
            "kind": "workspace_invalidation",
            "workspace_invalidation": {
                "state": safe_state,
                "action": action,
                "revision_changed": bool(revision_changed),
            },
        },
    }
    try:
        await stream_helpers.xadd(
            redis,
            f"chat:{thread_id}:stream",
            {"data": json.dumps(payload, separators=(",", ":"))},
        )
    except Exception:
        # Room invalidation is best-effort; its state is always available via REST.
        return
