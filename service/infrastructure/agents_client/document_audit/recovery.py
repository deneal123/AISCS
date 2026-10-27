"""Read-only private producer recovery; never sends fresh execution permission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from service.infrastructure.agents_client.document_audit.client import _AUDIT_STATUSES
from service.infrastructure.agents_client.document_audit.stream import AUDIT_PROTOCOL_PATH
from service.infrastructure.sidecar import SidecarClient, SidecarError
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal


@dataclass(frozen=True, slots=True)
class AuditRecoverySnapshot:
    state: str
    checkpoint: dict | None = None
    outcome: dict | None = None


def decode_snapshot(value: object, *, attempt_id: UUID) -> AuditRecoverySnapshot:
    try:
        if not isinstance(value, dict):
            raise ValueError
        state = value.get("state")
        if state in {"unknown", "unavailable"} and set(value) == {"state"}:
            return AuditRecoverySnapshot(state)
        if state not in {"active", "terminal"} or set(value) != {"state", "checkpoint", "result"}:
            raise ValueError
        checkpoint = value["checkpoint"]
        if checkpoint is not None:
            journal = UsageJournal.decode(checkpoint)
            if journal.attempt_id != str(attempt_id) or any(
                item.kind != "document_visual_audit" for item in journal.receipts
            ):
                raise ValueError
            checkpoint = journal.payload()
        result = value["result"]
        if state == "active":
            if result is not None:
                raise ValueError
            return AuditRecoverySnapshot(state, checkpoint)
        if not isinstance(result, dict) or set(result) != {"status", "passed", "retryable"}:
            raise ValueError
        if not isinstance(result["status"], str) or result["status"] not in _AUDIT_STATUSES:
            raise ValueError
        if type(result["passed"]) is not bool or type(result["retryable"]) is not bool:
            raise ValueError
        if (
            result["passed"] != (result["status"] == "passed")
            or result["passed"]
            and result["retryable"]
        ):
            raise ValueError
        if result["passed"] and checkpoint is None:
            raise ValueError
        return AuditRecoverySnapshot(state, checkpoint, dict(result))
    except Exception:
        return AuditRecoverySnapshot("unavailable")


async def recover_document_audit(
    config: Any,
    *,
    workspace_ref: dict,
    build_id: str,
    attempt_id: UUID,
) -> AuditRecoverySnapshot:
    agents = getattr(config, "agents", None)
    client = SidecarClient(
        service="agents",
        base_url=str(getattr(agents, "sidecar_url", "") or ""),
        timeout=15.0,
        api_key=str(getattr(agents, "llm_gateway_api_key", "") or ""),
    )
    try:
        value = await client.request_json(
            "POST",
            AUDIT_PROTOCOL_PATH,
            json_body={
                "workspace_ref": workspace_ref,
                "build_id": build_id,
                "checkpoint_attempt_id": str(attempt_id),
                "recovery_only": True,
            },
        )
    except SidecarError:
        return AuditRecoverySnapshot("unavailable")
    return decode_snapshot(value, attempt_id=attempt_id)
