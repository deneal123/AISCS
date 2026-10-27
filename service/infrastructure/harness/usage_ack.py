"""Один повтор записи точного usage после чтения; inference/dispatch не повторяются."""

from collections.abc import Awaitable, Callable
from typing import Any

from service.shared.harness_protocol import CallReceipt, HarnessFailure, OperationStatus


async def repost_model_confirmation(
    receipt: CallReceipt, status: OperationStatus, query: Callable[..., Awaitable[dict[str, Any]]]
) -> dict[str, Any] | None:
    if (
        receipt.status != "succeeded"
        or status.operation_id != receipt.operation_id
        or status.operation_kind != "paid"
        or receipt.estimated
        or receipt.message is None
        or receipt.prompt + receipt.completion == 0
        or status.status not in {"dispatched", "unknown"}
    ):
        return None
    try:
        response = await query(opcode="call_receipt", receipt=receipt)
        if (response.get("operation") or {}).get("status") == "succeeded":
            return response
    except HarnessFailure as error:
        if error.code not in {"checkpoint_unavailable", "operation_unknown"}:
            raise
    # Сам повтор тоже мог потерять ACK. Разрешено лишь ещё одно чтение того же ID.
    raw = await query(
        opcode="operation_status", operation_id=receipt.operation_id, operation_kind="paid"
    )
    confirmed = OperationStatus.model_validate(raw["operation_status"])
    if (
        confirmed.operation_id != receipt.operation_id
        or confirmed.operation_kind != "paid"
        or confirmed.status != "succeeded"
        or confirmed.receipt != receipt
    ):
        return None
    return {"operation": {"status": "succeeded", "receipt": receipt.model_dump(mode="json")}}
