"""Evidence required before removing or forgetting an ephemeral compiler."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable

Command = Callable[..., Awaitable[tuple[int, bytes]]]


class CompilerInventoryInvalid(ValueError):
    """A successful command returned an inventory that cannot prove identity."""


async def compiler_inventory(command: Command) -> frozenset[str]:
    """A successful complete inventory counts all labeled resources, not only jobs."""
    code, raw = await command(
        "docker", "ps", "-aq", "--no-trunc", "--filter", "label=gpthub.document=1", timeout=30.0
    )
    if code:
        raise ValueError("compiler inventory unavailable")
    if len(raw) > 1024 * 1024:
        raise CompilerInventoryInvalid("compiler inventory invalid")
    try:
        identifiers = raw.decode().splitlines()
    except UnicodeError:
        raise CompilerInventoryInvalid("compiler inventory invalid") from None
    if any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in identifiers) or len(
        set(identifiers)
    ) != len(identifiers):
        raise CompilerInventoryInvalid("compiler inventory invalid")
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
        expiry = labels.get("gpthub.document.expires_at")
        # Issued by prepare as a positive decimal Unix timestamp. Missing or
        # malformed metadata is unknown, not permission to destroy an orphan.
        if not isinstance(expiry, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", expiry):
            return None
        expires_at = float(expiry)
    except (TypeError, ValueError, UnicodeError):
        return None
    return expires_at, state == "true"
