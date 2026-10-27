"""Замороженный запрос и единственный платный model-call на шаг continuation."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from service.services.chat.persistence.harness.admission.calls import verified_wire_call
from service.shared.harness_protocol import Continuation, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload

_BODY_FIELDS = frozenset(
    {
        "messages",
        "model",
        "tools",
        "tool_choice",
        "functions",
        "function_call",
        "max_tokens",
        "max_completion_tokens",
        "temperature",
        "top_p",
        "stream",
        "seed",
        "response_format",
        "reasoning_effort",
        "parallel_tool_calls",
        "stop",
        "presence_penalty",
        "frequency_penalty",
    }
)


def request_messages(body: Mapping[str, Any]) -> list[dict]:
    return Continuation(messages=body.get("messages", []), phase="model").conversation()


def require_codec_transition(old: Continuation, new: Continuation) -> None:
    if (old.messages or old.call_payload_version == 2) and (
        old.call_payload_version != new.call_payload_version
    ):
        raise HarnessFailure("provider_state_incompatible")


def matching_request(existing: Mapping[str, Any], call: PaidCall) -> bool:
    raw = existing["request"]
    try:
        saved = PaidCall.model_validate(verified_wire_call(raw, existing["request_digest"]))
    except ValueError:
        return False
    return saved == call


def require_frozen_request(row: Mapping[str, Any], call: PaidCall) -> None:
    continuation = Continuation.model_validate(row.get("continuation") or {})
    if call.canonical_request is not None:
        try:
            body = json.loads(call.canonical_request)
            if (
                not isinstance(body, dict)
                or set(body) - _BODY_FIELDS
                or digest_payload(body) != call.request_digest
                or body.get("model") not in {None, call.model}
                or len(call.canonical_request.encode("utf-8")) + 1024 > call.prompt
                or any(
                    value is not None
                    and (type(value) is not int or not 0 < value <= call.completion)
                    for value in (body.get("max_tokens"), body.get("max_completion_tokens"))
                )
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise HarnessFailure("provider_state_incompatible") from None
    if call.continuation_step is None:
        if call.kind == "chat" and not call.billing_tool and continuation.call_payload_version == 2:
            raise HarnessFailure("provider_state_incompatible")
        return
    binding = continuation.provider
    if (
        call.billing_tool
        or call.kind != "chat"
        or call.canonical_request is None
        or continuation.call_payload_version != 2
        or continuation.phase != "model"
        or call.continuation_step != continuation.next_step
        or binding is None
        or (binding.provider, binding.model) != (call.provider, call.model)
    ):
        raise HarnessFailure("provider_state_incompatible")
    try:
        if request_messages(body) != continuation.conversation():
            raise ValueError()
    except (ValueError, TypeError):
        raise HarnessFailure("provider_state_incompatible") from None


def require_unique_step(call: PaidCall, grants: Sequence[Mapping[str, Any]]) -> None:
    if call.continuation_step is None:
        return
    if any(
        item["request"].get("continuation_step") == call.continuation_step
        and item["request"].get("kind", "chat") == "chat"
        and not item["request"].get("billing_tool")
        for item in grants
    ):
        raise HarnessFailure("provider_state_incompatible")
