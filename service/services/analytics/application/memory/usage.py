"""Private memory usage projection retaining immutable gateway receipts."""

from typing import Any
from uuid import uuid4

_FIELDS = frozenset(
    {"receipt_id", "model", "provider", "prompt", "completion", "total", "kind", "estimated"}
)


def accumulate_memory_usage(
    out: dict[str, Any], usage: dict[str, Any], fallback_model: str
) -> None:
    calls = usage.get("calls")
    if not isinstance(calls, list) or not calls:
        # Give an older aggregate one local identity, preserving its legacy price
        # label without claiming that the provider was confirmed.
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        if prompt + completion == 0:
            prompt = int(usage.get("total_tokens") or 0)
        calls = [
            {
                "receipt_id": uuid4().hex,
                "model": usage.get("model") or fallback_model,
                "prompt": prompt,
                "completion": completion,
            }
        ]
    if isinstance(calls, list) and calls:
        accepted = [dict(call) for call in out.get("calls", [])]
        indexed = {call["receipt_id"]: call for call in accepted}
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("receipt_id"), str):
                raise ValueError("invalid_usage_receipt")
            receipt = {key: value for key, value in call.items() if key in _FIELDS}
            for field in ("prompt", "completion"):
                value = receipt.get(field)
                if type(value) is not int or value < 0:
                    raise ValueError("invalid_usage_receipt")
            receipt["total"] = receipt["prompt"] + receipt["completion"]
            previous = indexed.get(receipt["receipt_id"])
            if previous is not None:
                if previous != receipt:
                    raise ValueError("usage_receipt_conflict")
                continue
            indexed[receipt["receipt_id"]] = receipt
            accepted.append(receipt)
        models = {call.get("model") for call in accepted}
        out.update(
            calls=accepted,
            prompt=sum(call["prompt"] for call in accepted),
            completion=sum(call["completion"] for call in accepted),
            total=sum(call["total"] for call in accepted),
            model=next(iter(models)) if len(models) == 1 else None,
        )
        return
