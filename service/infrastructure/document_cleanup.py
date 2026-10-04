"""Evidence required before removing or forgetting an ephemeral compiler."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable

Command = Callable[..., Awaitable[tuple[int, bytes]]]


async def compiler_inventory(command: Command) -> frozenset[str]:
    """A successful complete inventory counts all labeled resources, not only jobs."""
    code, raw = await command(
        "docker", "ps", "-aq", "--no-trunc", "--filter", "label=gpthub.document=1", timeout=30.0
    )
    if code or len(raw) > 1024 * 1024:
        raise ValueError("compiler inventory unavailable")
    identifiers = raw.decode().splitlines()
    if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in identifiers) or len(
        set(identifiers)
    ) != len(identifiers):
        raise ValueError("compiler inventory invalid")
    return frozenset(identifiers)


async def container_absent(command: Command, container_id: str) -> bool:
    """Only an exact ID and successful full inventory can prove absence."""
    if not re.fullmatch(r"[0-9a-f]{64}", container_id):
        return False
    code, inventory = await command("docker", "ps", "-aq", "--no-trunc", timeout=30.0)
    identifiers = inventory.decode().splitlines()
    return (
        code == 0
        and all(re.fullmatch(r"[0-9a-f]{64}", item) for item in identifiers)
        and container_id not in identifiers
    )


async def compiler_state(command: Command, container_id: str) -> tuple[float, bool] | None:
    """Return observed expiry/running state; unknown is never stopped/expired."""
    labels_code, labels_raw = await command(
        "docker", "inspect", "--format", "{{json .Config.Labels}}", container_id, timeout=15.0
    )
    if labels_code:
        return None
    state_code, state_raw = await command(
        "docker", "inspect", "--format", "{{.State.Running}}", container_id, timeout=15.0
    )
    if state_code:
        return None
    try:
        labels = json.loads(labels_raw)
        state = state_raw.decode().strip().lower()
        if not isinstance(labels, dict) or state not in {"true", "false"}:
            return None
        expires_at = float(labels.get("gpthub.document.expires_at") or 0)
        if not math.isfinite(expires_at):
            return None
    except (TypeError, ValueError, UnicodeError):
        return None
    return expires_at, state == "true"
