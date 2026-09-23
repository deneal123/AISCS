"""Private metered visual-audit call into the agents sidecar."""

from __future__ import annotations

from typing import Any

from service.infrastructure.sidecar import SidecarClient, SidecarError


def _bounded_usage(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("calls"), list):
        return {}
    calls: list[dict] = []
    for item in value["calls"][:16]:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or "")[:128]
        try:
            prompt = max(0, int(item.get("prompt") or 0))
            completion = max(0, int(item.get("completion") or 0))
        except (TypeError, ValueError):
            continue
        if not model or prompt + completion < 1:
            continue
        calls.append(
            {
                "model": model,
                "prompt": prompt,
                "completion": completion,
                **({"provider": str(item["provider"])[:64]} if item.get("provider") else {}),
                **({"kind": str(item["kind"])[:64]} if item.get("kind") else {}),
                **({"estimated": True} if item.get("estimated") else {}),
            }
        )
    prompt = sum(int(item["prompt"]) for item in calls)
    completion = sum(int(item["completion"]) for item in calls)
    if not calls:
        return {}
    models = {str(item["model"]) for item in calls}
    return {
        "prompt": prompt,
        "completion": completion,
        "total": prompt + completion,
        "calls": calls,
        **({"model": next(iter(models))} if len(models) == 1 else {}),
    }


async def audit_document(config: Any, *, workspace_ref: dict, build_id: str) -> dict:
    agents = getattr(config, "agents", None)
    client = SidecarClient(
        service="agents",
        base_url=str(getattr(agents, "sidecar_url", "") or ""),
        timeout=180.0,
        api_key=str(getattr(agents, "llm_gateway_api_key", "") or ""),
    )
    try:
        result = await client.request_json(
            "POST",
            "/document-audit",
            json_body={"workspace_ref": workspace_ref, "build_id": build_id},
        )
    except SidecarError:
        return {"status": "unavailable", "passed": False, "retryable": True}
    if not isinstance(result, dict):
        return {"status": "protocol", "passed": False, "retryable": True}
    usage = _bounded_usage(result.get("usage"))
    return {
        "status": str(result.get("status") or "protocol")[:64],
        "passed": bool(result.get("passed")),
        "retryable": bool(result.get("retryable", True)),
        "usage": usage,
    }


__all__ = ["audit_document"]
