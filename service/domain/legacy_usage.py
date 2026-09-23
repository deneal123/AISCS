"""Isolated mutable-usage compatibility for direct legacy callers.

Production execution records provider calls in :class:`UsageLedger`.  This module is
the only permitted place that projects an existing receipt into the historical mutable
dictionary accepted by older unit helpers and SDK adapters.
"""

from __future__ import annotations

from typing import Any

from service.domain.run_context import current_execution
from service.domain.usage_ledger import UsageReceipt


def project_receipt(usage_out: dict[str, Any] | None, receipt: UsageReceipt) -> None:
    """Project one existing receipt; never create or charge a provider call."""

    if usage_out is None or not receipt.billable:
        return
    calls = usage_out.setdefault("calls", [])
    if any(
        isinstance(item, dict) and item.get("receipt_id") == receipt.receipt_id for item in calls
    ):
        return
    usage_out["prompt"] = int(usage_out.get("prompt", 0) or 0) + receipt.prompt
    usage_out["completion"] = int(usage_out.get("completion", 0) or 0) + receipt.completion
    usage_out["total"] = int(usage_out.get("total", 0) or 0) + receipt.total
    if receipt.model:
        usage_out["model"] = receipt.model
    if receipt.provider:
        usage_out["provider"] = receipt.provider
    if receipt.estimated:
        usage_out["estimated"] = True
    calls.append(receipt.as_dict())


def accumulate_usage(
    usage_out: dict[str, Any] | None,
    response: Any,
    model: str | None = None,
    *,
    kind: str | None = None,
) -> None:
    """Compatibility projection for a response already owned by the active ledger."""

    if usage_out is None:
        return
    execution = current_execution()
    receipt = execution.response_receipt(response) if execution is not None else None
    if receipt is None and execution is not None:
        provider, actual_model = execution.claim_response_provider(response)
        receipt = execution.usage.record_response(
            response,
            provider=provider,
            model=actual_model or model,
            kind=kind,
        )
        execution.register_response_receipt(response, receipt.receipt_id)
    if receipt is None:
        from service.domain.usage_ledger import receipt_from_response

        receipt = receipt_from_response(
            response,
            provider=None,
            model=model,
            kind=kind,
        )
    project_receipt(usage_out, receipt)


__all__ = ["accumulate_usage", "project_receipt"]


def extract_legacy_projection(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Remove only the historical usage keyword and preserve provider arguments."""

    projection = kwargs.pop("usage_out", None)
    return projection if isinstance(projection, dict) else None


__all__.append("extract_legacy_projection")
