"""Чтение оплаченного ответа при совместимом дрейфе настроек без нового inference."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from service.services.chat.persistence.harness.model_requests import (
    matching_request,
    request_messages,
    require_frozen_request,
)
from service.shared.harness_protocol import CallReceipt, Continuation, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload

_TUNING = frozenset({"temperature", "top_p", "seed", "max_tokens", "max_completion_tokens"})
_TOOLS = frozenset({"tools", "functions"})


def _functions(body: Mapping[str, Any]) -> dict[str, dict]:
    if body.get("functions") and body.get("tools"):
        raise ValueError()
    definitions = body.get("functions") or [
        item["function"] for item in body.get("tools", []) if item.get("type") == "function"
    ]
    result = {}
    for function in definitions:
        name = function["name"]
        if name in result:
            raise ValueError()
        result[name] = function
    return result


def _compatible(row, original: PaidCall, candidate: PaidCall, receipt: CallReceipt) -> bool:
    if (
        original.canonical_request is None
        or candidate.canonical_request is None
        or receipt.message is None
    ):
        return False
    old, new = json.loads(original.canonical_request), json.loads(candidate.canonical_request)
    continuation = Continuation.model_validate(row.get("continuation") or {})
    original_messages = request_messages(old)
    if original_messages != continuation.conversation():
        return False
    ignored = _TUNING | _TOOLS
    if {key: value for key, value in old.items() if key not in ignored} != {
        key: value for key, value in new.items() if key not in ignored
    }:
        return False
    offered, current = _functions(old), _functions(new)
    return all(
        (name := call.function["name"]) in offered
        and name in current
        and offered[name] == current[name]
        for call in receipt.message.tool_calls
    )


def completed_step_replay(
    row: Mapping[str, Any], call: PaidCall, grants: Sequence[Mapping[str, Any]]
) -> dict[str, Any] | None:
    if call.continuation_step is None:
        return None
    require_frozen_request(row, call)
    slots = [
        item
        for item in grants
        if item["request"].get("continuation_step") == call.continuation_step
        and item["request"].get("kind", "chat") == "chat"
        and not item["request"].get("billing_tool")
    ]
    if not slots:
        return None
    if len(slots) != 1 or slots[0]["state"] != "succeeded":
        raise HarnessFailure("provider_state_incompatible")
    saved = slots[0]
    try:
        original = PaidCall.model_validate(saved["request"])
        require_frozen_request(row, original)
        receipt = CallReceipt.model_validate(saved["receipt"])
        if (
            not matching_request(saved, original)
            or receipt.operation_id != original.operation_id
            or receipt.status != "succeeded"
            or receipt.estimated
            or receipt.message is None
            or receipt.prompt + receipt.completion == 0
            or receipt.prompt > original.prompt
            or receipt.completion > original.completion
            or (
                original.provider == "gigachat"
                and receipt.message.tool_calls
                and receipt.provider_state is None
            )
            or (
                receipt.provider_state is not None
                and (
                    receipt.provider_state.provider != original.provider
                    or receipt.provider_state.model != original.model
                )
            )
            or not _compatible(row, original, call, receipt)
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HarnessFailure("provider_state_incompatible") from None
    return {
        "status": "succeeded",
        "operation_id": original.operation_id,
        "tariff_digest": digest_payload(row["tariff"]),
        "receipt": saved["receipt"],
    }
