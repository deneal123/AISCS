"""Delivery of backend-owned workflow catalog outbox to the agents sidecar."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from service.infrastructure.sidecar import (
    SidecarBadRequest,
    SidecarClient,
    SidecarError,
    SidecarTimeout,
    SidecarUnavailable,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 30.0


@dataclass(frozen=True)
class DeliveryResult:
    delivered: bool
    error_class: str = ""


def _client(config: Any) -> SidecarClient:
    agents = getattr(config, "agents", None)
    return SidecarClient(
        service="agents",
        base_url=str(getattr(agents, "sidecar_url", "") or ""),
        timeout=_TIMEOUT_SEC,
        api_key=str(getattr(agents, "llm_gateway_api_key", "") or ""),
    )


async def deliver(config: Any, row: dict[str, Any]) -> DeliveryResult:
    """Project one safe outbox row. Request text is body-only embedding input, never logged."""
    action = str(row.get("action") or "")
    try:
        if action == "delete":
            await _client(config).request_json(
                "POST",
                "/workflow-catalog/delete",
                json_body={"point_id": str(row["index_point_id"])},
            )
            return DeliveryResult(True)
        request_text = str(row.get("request_text") or "")
        if not request_text:
            # Retention may remove an old example before a stale outbox retry. There is
            # nothing sensitive left to project, so complete it rather than retry forever.
            return DeliveryResult(True)
        await _client(config).request_json(
            "POST",
            "/workflow-catalog/upsert",
            json_body={
                "point_id": str(row["index_point_id"]),
                "workflow_id": str(row["workflow_id"]),
                "version": int(row["version"]),
                "name": str(row["name"]),
                "label_ru": str(row["label_ru"]),
                "steps": list(row["steps"] or []),
                "cost_class": str(row["cost_class"]),
                "state": str(row["state"]),
                "quality_score": float(row["quality_score"]),
                "reuse_score": float(row["reuse_score"]),
                "request_text": request_text,
            },
        )
        return DeliveryResult(True)
    except SidecarError as exc:
        code = _error_class(exc)
        logger.warning(
            "Workflow catalog delivery deferred: %s",
            code,
            extra={"component": "agents", "operation": "workflow_delivery", "failure_code": code},
        )
        return DeliveryResult(False, code)
    except Exception:  # noqa: BLE001 - maintenance must release the lease safely
        logger.warning(
            "Workflow catalog delivery deferred: unknown",
            extra={
                "component": "agents",
                "operation": "workflow_delivery",
                "failure_code": "unknown",
            },
        )
        return DeliveryResult(False, "unknown")


def _error_class(error: SidecarError) -> str:
    # Remote error text is not a classifier. Typed timeout wins over remote codes.
    if isinstance(error, SidecarTimeout):
        return "timeout"
    if error.code in {"timeout", "server_deadline"}:
        return "timeout"
    if error.code in {"transport_error", "connection_error"}:
        return "transport"
    if error.code in {"protocol_error", "decode_error", "invalid_json"}:
        return "protocol"
    if error.code == "not_configured":
        return "unknown"
    if isinstance(error, (SidecarBadRequest, SidecarUnavailable)):
        return "remote"
    if error.code in {"http_error", "remote_error"}:
        return "remote"
    return "unknown"
