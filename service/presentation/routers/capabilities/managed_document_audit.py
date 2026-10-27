"""Private producer lifecycle: explicit ownership, durable receipts, sealed outcome."""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from service.infrastructure.document_audit.registry import (
    AuditProducerRegistry,
    AuditRegistryUnavailable,
)
from service.presentation.routers.capabilities.audit_checkpoint_barrier import (
    AuditCheckpointBarrier,
)
from service.shared.redis_client import get_redis


def registry_for(payload: Any) -> AuditProducerRegistry:
    try:
        owner = str(UUID(payload.workspace_ref["user_id"]))
        workspace = payload.workspace_ref["workspace_id"]
        if (
            not isinstance(workspace, str)
            or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", workspace) is None
        ):
            raise ValueError
        digest = hashlib.sha256(
            json.dumps([owner, workspace, payload.build_id]).encode()
        ).hexdigest()
        return AuditProducerRegistry(
            get_redis(), attempt_id=str(payload.checkpoint_attempt_id), scope_digest=digest
        )
    except Exception:
        raise AuditRegistryUnavailable() from None


def recovered_outcome(snapshot: dict) -> dict:
    if snapshot["state"] != "terminal":
        return {"status": "unavailable", "passed": False, "retryable": True, "usage": {}}
    calls = (snapshot.get("checkpoint") or {}).get("receipts", [])
    prompt = sum(call["prompt"] for call in calls)
    completion = sum(call["completion"] for call in calls)
    return {
        **snapshot["result"],
        "usage": {
            "calls": calls,
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
        },
    }


async def execute_managed_audit(payload: Any, execute: Callable[..., Awaitable[dict]]) -> dict:
    barrier: AuditCheckpointBarrier | None = None
    try:
        registry = registry_for(payload)
        if not await registry.claim(fresh_attempt=payload.fresh_attempt):
            return recovered_outcome(await registry.snapshot())
        barrier = AuditCheckpointBarrier(registry)

        async def finish(result: dict) -> None:
            async with asyncio.timeout(4):
                if barrier.ledger is not None:
                    await barrier.flush(barrier.ledger)
                await registry.seal({key: result[key] for key in ("status", "passed", "retryable")})

        try:
            result = await execute(payload, usage_checkpoint=barrier.flush)
        except asyncio.CancelledError:
            try:
                await finish({"status": "cancelled", "passed": False, "retryable": True})
            except Exception:
                pass  # No seal without persisted expense; recovery remains unresolved.
            raise
        except Exception:
            result = {
                "status": "internal",
                "passed": False,
                "retryable": True,
                "usage": barrier.ledger.project_since(0) if barrier.ledger is not None else {},
            }
        await finish(result)
        return result
    except Exception:
        usage = (
            barrier.ledger.project_since(0)
            if barrier is not None and barrier.ledger is not None
            else {}
        )
        return {"status": "unavailable", "passed": False, "retryable": True, "usage": usage}
    finally:
        if barrier is not None:
            barrier.close()
