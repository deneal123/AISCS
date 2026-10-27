"""Private metered visual-audit call into the agents sidecar."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import aclosing
from typing import Any
from uuid import UUID

from service.infrastructure import provider_policy_store as provider_policy
from service.infrastructure.agents_client.contracts.usage_identity import safe_usage_identity
from service.infrastructure.agents_client.contracts.usage_kinds import SERVICE_USAGE_KINDS
from service.infrastructure.agents_client.document_audit.stream import (
    AUDIT_PROTOCOL_PATH,
    consume_audit_frames,
)
from service.infrastructure.agents_client.provider_policy_snapshot import build_snapshot
from service.infrastructure.sidecar import SidecarClient, SidecarError

_AUDIT_STATUSES = frozenset(
    {
        "passed",
        "failed",
        "invalid",
        "page_limit",
        "vision_unavailable",
        "workspace_unavailable",
        "unavailable",
        "timeout",
        "transport",
        "remote",
        "protocol",
        "conflict",
        "expired",
        "cancelled",
        "policy",
        "internal",
    }
)


def _usage_identity(value: object) -> str | None:
    return safe_usage_identity(value, max_length=128)


def _remember_receipt(calls: list[dict], receipts: dict[str, dict], call: dict) -> bool:
    identity = call.get("receipt_id")
    previous = receipts.get(identity) if identity is not None else None
    if previous is None:
        calls.append(call)
        if identity is not None:
            receipts[identity] = call
        return True
    if previous == call:
        return True
    provenance = ("model", "provider", "kind")
    if any(previous.get(key) != call.get(key) for key in provenance):
        return False
    if previous.get("estimated") and not call.get("estimated"):
        # Match the ledger: exact usage refines the same accepted call.
        previous.clear()
        previous.update(call)
        return True
    if not previous.get("estimated") and call.get("estimated"):
        return True  # A stale estimate cannot replace the exact receipt.
    return False


def _bounded_usage(value: object) -> dict:
    return _project_usage(value)[0]


def _project_usage(value: object) -> tuple[dict, bool]:
    if not isinstance(value, dict) or not isinstance(value.get("calls"), list):
        return {}, True
    calls: list[dict] = []
    receipts: dict[str, dict] = {}
    consistent = True
    # The producer bounds page count/batches. Never truncate accepted costs:
    # the supported 200-page audit alone can have 50 separate receipts.
    for item in value["calls"]:
        if not isinstance(item, dict):
            continue
        model = _usage_identity(item.get("model"))
        receipt_id = _usage_identity(item.get("receipt_id"))
        provider = item.get("provider")
        kind = item.get("kind")
        try:
            prompt = max(0, int(item.get("prompt") or 0))
            completion = max(0, int(item.get("completion") or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if prompt + completion < 1:
            continue
        call = {
            "model": model,
            "prompt": prompt,
            "completion": completion,
            **({"receipt_id": receipt_id} if receipt_id is not None else {}),
            **({"provider": provider} if provider in provider_policy.PROVIDER_NAMES else {}),
            **({"kind": kind} if isinstance(kind, str) and kind in SERVICE_USAGE_KINDS else {}),
            **({"estimated": True} if item.get("estimated") else {}),
        }
        consistent = _remember_receipt(calls, receipts, call) and consistent
    prompt = sum(int(item["prompt"]) for item in calls)
    completion = sum(int(item["completion"]) for item in calls)
    if not calls:
        return {}, consistent
    models = {item["model"] for item in calls}
    return {
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
        "calls": calls,
        **({"model": next(iter(models))} if len(models) == 1 and None not in models else {}),
    }, consistent


async def audit_document(
    config: Any,
    *,
    workspace_ref: dict,
    build_id: str,
    checkpoint_attempt_id: UUID | None = None,
    checkpoint_sink: Callable[[dict], Awaitable[None]] | None = None,
    fresh_attempt: bool = False,
) -> dict:
    if (checkpoint_attempt_id is None) != (checkpoint_sink is None) or (
        checkpoint_attempt_id is not None and fresh_attempt is not True
    ):
        return {"status": "protocol", "passed": False, "retryable": True}
    try:
        policy = build_snapshot(
            disabled=provider_policy.disabled_providers(),
            blocked=await provider_policy.blocked_providers(),
        )
    except Exception:
        # No metered call may bypass admin policy because its snapshot failed.
        # Preserve the durable job for retry, without exception details.
        return {"status": "unavailable", "passed": False, "retryable": True}
    agents = getattr(config, "agents", None)
    client = SidecarClient(
        service="agents",
        base_url=str(getattr(agents, "sidecar_url", "") or ""),
        timeout=180.0,
        api_key=str(getattr(agents, "llm_gateway_api_key", "") or ""),
    )
    try:
        payload = {"workspace_ref": workspace_ref, "build_id": build_id, "provider_policy": policy}
        if checkpoint_attempt_id is not None and checkpoint_sink is not None:
            payload["checkpoint_attempt_id"] = str(checkpoint_attempt_id)
            payload["fresh_attempt"] = True
            async with aclosing(
                client.request_ndjson(
                    "POST",
                    AUDIT_PROTOCOL_PATH,
                    json_body=payload,
                )
            ) as frames:
                result = await consume_audit_frames(
                    frames,
                    attempt_id=checkpoint_attempt_id,
                    persist=checkpoint_sink,
                )
        else:
            result = await client.request_json("POST", "/document-audit", json_body=payload)
    except SidecarError:
        return {
            "status": "unavailable",
            "passed": False,
            "retryable": True,
            **({"producer_unresolved": True} if checkpoint_attempt_id is not None else {}),
        }
    if not isinstance(result, dict):
        return {"status": "protocol", "passed": False, "retryable": True}
    usage, consistent = _project_usage(result.get("usage"))
    status = result.get("status")
    passed = result.get("passed", False)
    retryable = result.get("retryable", not passed)
    if (
        not consistent
        or not isinstance(status, str)
        or status not in _AUDIT_STATUSES
        or type(passed) is not bool
        or type(retryable) is not bool
        or passed != (status == "passed")
        or (passed and retryable)
    ):
        # Protocol failure must never certify a PDF or discard accepted usage.
        return {
            "status": "protocol",
            "passed": False,
            "retryable": True,
            "usage": usage,
            **({"producer_unresolved": True} if checkpoint_attempt_id is not None else {}),
        }
    return {
        "status": status,
        "passed": passed,
        "retryable": retryable,
        "usage": usage,
    }


__all__ = ["audit_document"]
