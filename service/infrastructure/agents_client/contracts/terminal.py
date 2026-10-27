"""Minimal structural acceptance shared by transport and cooperative cancellation."""

from typing import Any


def valid_run_result(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("reply"), str):
        return False
    metadata = value.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        return False
    calls = value.get("per_call_usage")
    return calls is None or (
        isinstance(calls, list) and all(isinstance(item, dict) for item in calls)
    )
