"""Provision and clean an isolated workspace for the opt-in GigaChat smoke.

Run inside the backend container. The JSON output is a private pipe between backend and
agents containers; Make never echoes it. Cleanup accepts only identifiers created by
this module, so an accidental payload cannot destroy a normal chat workspace.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from typing import Any

from service.infrastructure.cache.redis_manager import RedisManager
from service.infrastructure.workspace_client import ensure_workspace_explicit, release_workspace
from service.services.chat.application.workspace_collaboration import mint_capability
from service.settings import config

_PREFIX = "s25-smoke-"


def _new_identity() -> tuple[str, str]:
    suffix = secrets.token_hex(8)
    return f"{_PREFIX}{suffix}", f"{_PREFIX}{suffix}"


def _read_private_payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise RuntimeError("invalid_fixture_payload") from None
    ref = value.get("workspace_ref") if isinstance(value, dict) else None
    if not isinstance(ref, dict):
        raise RuntimeError("invalid_fixture_payload")
    return value


def _is_owned_fixture(ref: dict[str, Any]) -> bool:
    thread_id = str(ref.get("thread_id") or "")
    user_id = str(ref.get("user_id") or "")
    return thread_id.startswith(_PREFIX) and user_id.startswith(_PREFIX) and thread_id == user_id


async def _provision(redis) -> dict[str, Any]:
    thread_id, user_id = _new_identity()
    ref = await ensure_workspace_explicit(redis, thread_id, user_id)
    if not ref:
        raise RuntimeError("workspace_provision_failed")
    ref = {
        **ref,
        "coordination_capability": mint_capability(
            str(ref["workspace_id"]),
            role="agent",
            actor_seed=f"{thread_id}:{user_id}",
            expires_at=float(ref.get("expires_at") or 0),
            run_id=thread_id,
        ),
    }
    return {"workspace_ref": ref, "marker": f"s25-{secrets.token_urlsafe(18)}"}


async def _run(command: str) -> None:
    manager = RedisManager(config.redis)
    redis = manager.get_client()
    try:
        if command == "provision":
            print(json.dumps(await _provision(redis), ensure_ascii=True, separators=(",", ":")))
            return
        if command == "cleanup":
            payload = _read_private_payload()
            ref = payload["workspace_ref"]
            if not _is_owned_fixture(ref):
                raise RuntimeError("fixture_ownership_invalid")
            await release_workspace(redis, str(ref["thread_id"]))
            return
        raise RuntimeError("unsupported_fixture_command")
    finally:
        await manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(_run(sys.argv[1] if len(sys.argv) == 2 else ""))
    except Exception as exc:  # noqa: BLE001 - operational diagnostics stay bounded
        print(f"workspace fixture: FAILED ({type(exc).__name__})", file=sys.stderr)
        raise SystemExit(1) from None
