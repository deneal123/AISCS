"""Одинаковый digest исходного запроса и его JSON checkpoint-представления."""

from service.shared.harness_protocol import (
    CallReceipt,
    Continuation,
    HarnessFailure,
    TranscriptMessage,
)
from service.shared.task_contract import canonical_uuid


def receipt_finish_reason(receipt: dict) -> str:
    reason = receipt.get("finish_reason")
    if reason not in {"stop", "length", "tool_calls", "function_call", "content_filter"}:
        raise HarnessFailure("provider_state_incompatible")
    return reason


def replay_receipt(requested_id: str, operation: dict) -> tuple[str, dict]:
    try:
        operation_id = canonical_uuid(operation.get("operation_id", requested_id))
        receipt = CallReceipt.model_validate(operation["receipt"])
        if (
            receipt.operation_id != operation_id
            or receipt.status != "succeeded"
            or receipt.estimated
            or receipt.message is None
            or receipt.prompt + receipt.completion == 0
        ):
            raise ValueError()
        return operation_id, operation["receipt"]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HarnessFailure("provider_state_incompatible") from None


def require_replay_codec(continuation: Continuation) -> None:
    if continuation.messages and continuation.call_payload_version != 2:
        raise HarnessFailure("provider_state_incompatible")


def canonical_call_payload(payload: dict) -> dict:
    clean = {
        key: value
        for key, value in payload.items()
        if key not in {"client", "_provider_session", "provider_session"}
    }
    if "messages" not in clean:
        return clean
    try:
        messages = []
        for value in clean["messages"]:
            message = TranscriptMessage.model_validate(value).model_dump(
                mode="json", exclude_none=True
            )
            if not message.get("tool_calls"):
                message.pop("tool_calls", None)
            messages.append(message)
        clean["messages"] = messages
    except (ValueError, TypeError):
        raise HarnessFailure("provider_state_incompatible") from None
    return clean
