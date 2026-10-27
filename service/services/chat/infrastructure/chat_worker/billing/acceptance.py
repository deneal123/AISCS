"""Distinguish a pre-acceptance service refusal from a model answer without usage."""

from typing import Any

from service.services.chat.infrastructure.pricing_signals import _pricing_signals


def failed_without_paid_work(
    result: dict[str, Any], pricing_inputs: tuple[bool, list[str]] | None
) -> bool:
    metadata = result.get("metadata")
    # A deterministic confirmation offer is not a model answer with lost usage.
    # Accepted meta calls still have receipts and must settle normally.
    service_only = isinstance(metadata, dict) and (
        metadata.get("execution_status") == "failed"
        or (
            metadata.get("execution_status") == "deferred"
            and isinstance(metadata.get("mode_offer"), dict)
        )
    )
    return (
        int(result.get("total_tokens") or 0) <= 0
        and not result.get("per_call_usage")
        and service_only
        and not (pricing_inputs or _pricing_signals(result))[1]
    )
