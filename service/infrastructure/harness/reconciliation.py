"""Сверка потерянного ACK по точной записи journal.

Dispatch ACK не восстанавливается повторным запуском. После чтения допустим один
повтор сохранения известного точного model receipt; provider/workspace эффекты
никогда не повторяются этим модулем.
"""

from service.infrastructure.harness.usage_ack import repost_model_confirmation
from service.infrastructure.harness.write_ack import reconciled_write_snapshot
from service.shared.harness_protocol import Exchange, OperationStatus, Snapshot
from service.shared.task_contract import digest_payload

_INTENTS = {"grant": ("call", "paid"), "prepare_effect": ("effect", "effect")}
_RECEIPTS = {"call_receipt": ("receipt", "paid"), "effect_receipt": ("effect_result", "effect")}


async def reconcile_exchange(request: Exchange, prior: Snapshot | None, query) -> dict | None:
    if request.opcode == "checkpoint" and prior is not None:
        return await _checkpoint(request, prior, query)
    spec = _INTENTS.get(request.opcode) or _RECEIPTS.get(request.opcode)
    if spec is None:
        return None
    field, kind = spec
    value = getattr(request, field)
    raw = await query(
        opcode="operation_status", operation_id=value.operation_id, operation_kind=kind
    )
    status = OperationStatus.model_validate(raw["operation_status"])
    if status.operation_id != value.operation_id or status.operation_kind != kind:
        return None
    if request.opcode in _INTENTS:
        if status.request_digest != digest_payload(value.model_dump(mode="json")):
            return None
        allowed = (
            {"allocated", "succeeded"} if kind == "paid" else {"prepared", "succeeded", "failed"}
        )
        if status.status not in allowed:
            return None
    else:
        if request.opcode == "effect_receipt":
            snapshot = await reconciled_write_snapshot(value, status.receipt, prior, query)
            if snapshot is not None:
                return {
                    "snapshot": snapshot,
                    "operation": {
                        "status": status.status,
                        "receipt": status.receipt.model_dump(mode="json"),
                    },
                }
        if status.receipt != value:
            if request.opcode == "call_receipt":
                return await repost_model_confirmation(value, status, query)
            return None
    return {
        "operation": {
            "status": status.status,
            "receipt": status.receipt.model_dump(mode="json") if status.receipt else None,
        }
    }


async def _checkpoint(request: Exchange, prior: Snapshot, query) -> dict | None:
    raw = await query(opcode="state")
    current = Snapshot.model_validate(raw["snapshot"])
    if (
        current.admission != prior.admission
        or current.revision != request.expected_revision + 1
        or current.continuation != request.continuation
        or current.stopped
    ):
        return None
    if prior.state is None:
        if (
            current.state is None
            and request.state is None
            and request.continuation.phase == "admitting"
        ):
            return {"snapshot": current.model_dump(mode="json")}
        return None
    if current.state is None:
        return None
    expected = request.state or prior.state
    target = expected.model_dump(mode="json")
    if expected != prior.state:
        target["revision"] = prior.state.revision + 1
    if current.state.model_dump(mode="json") != target:
        return None
    return {"snapshot": current.model_dump(mode="json")}
