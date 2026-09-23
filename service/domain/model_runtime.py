"""Ledger-native invocation seam for non-stream model calls."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from service.domain.client.protocol import ModelCallResult, ProviderRunSession
from service.domain.llm_response import first_message_content
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.usage_ledger import UsageKind, UsageReceipt, receipt_from_response
from service.shared.token_budget import estimate_tokens

ModelCallable = Callable[..., Awaitable[Any]]


def _finish_reason(response: Any) -> str | None:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    value = str(getattr(choices[0], "finish_reason", "") or "").strip()
    return value or None


def _estimated_usage(kwargs: dict[str, Any], response: Any) -> dict[str, int | bool]:
    prompt_payload = {
        "messages": kwargs.get("messages") or [],
        "tools": kwargs.get("tools") or [],
    }
    prompt = estimate_tokens(json.dumps(prompt_payload, ensure_ascii=False, default=str))
    completion = estimate_tokens(first_message_content(response))
    return {
        "prompt": max(1, prompt),
        "completion": max(1, completion),
        "estimated": True,
    }


def _receipt_for_result(
    response: Any,
    *,
    requested_model: str | None,
    kind: str | UsageKind | None,
    kwargs: dict[str, Any],
    provider_session: ProviderRunSession | None,
    provider_name: str | None,
    chargeable: bool,
    estimate_missing_usage: bool,
    execution: RunExecutionContext,
) -> tuple[str, str | None, str | None, UsageReceipt]:
    if provider_session is not None and provider_session.rounds:
        round_receipt = provider_session.rounds[-1]
        existing = provider_session.usage.get(round_receipt.usage_receipt_id)
        if existing is None or existing.total <= 0:
            usage = _estimated_usage(kwargs, response)
            existing = provider_session.usage.record_usage(
                usage,
                provider=round_receipt.provider,
                model=round_receipt.model,
                kind=kind,
                receipt_id=round_receipt.call_id,
                estimated=True,
            )
        execution.register_response_receipt(response, existing.receipt_id)
        return round_receipt.call_id, round_receipt.provider, round_receipt.model, existing

    provider: str | None = provider_name
    model = requested_model
    claimed_provider, actual_model = execution.claim_response_provider(response)
    provider = claimed_provider or provider
    model = actual_model or model
    call_id = uuid4().hex
    receipt = receipt_from_response(
        response,
        provider=provider,
        model=model,
        kind=kind,
        receipt_id=call_id,
        chargeable=chargeable,
    )
    if receipt.total <= 0 and estimate_missing_usage:
        estimated = _estimated_usage(kwargs, response)
        from service.domain.usage_ledger import receipt_from_usage

        receipt = receipt_from_usage(
            estimated,
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=call_id,
            estimated=True,
            chargeable=chargeable,
        )
    execution.usage.record(receipt)
    execution.register_response_receipt(response, receipt.receipt_id)
    return call_id, provider, model, receipt


async def invoke_model_call(
    call: ModelCallable,
    *,
    model: str | None,
    kind: str | UsageKind | None,
    execution: RunExecutionContext | None = None,
    provider_session: ProviderRunSession | None = None,
    provider_name: str | None = None,
    chargeable: bool = True,
    estimate_missing_usage: bool = True,
    **kwargs: Any,
) -> ModelCallResult:
    """Execute exactly one logical model call and create exactly one receipt."""

    execution = require_execution(execution)
    call_kwargs = dict(kwargs)
    if model is not None:
        call_kwargs["model"] = model
    if provider_session is not None:
        call_kwargs["provider_session"] = provider_session
    response = await call(**call_kwargs)
    call_id, provider, actual_model, receipt = _receipt_for_result(
        response,
        requested_model=model,
        kind=kind,
        kwargs=call_kwargs,
        provider_session=provider_session,
        provider_name=provider_name,
        chargeable=chargeable,
        estimate_missing_usage=estimate_missing_usage,
        execution=execution,
    )
    return ModelCallResult(
        response=response,
        call_id=call_id,
        provider=provider,
        model=actual_model,
        finish_reason=_finish_reason(response),
        usage=receipt,
    )


def record_estimated_model_call(
    *,
    model: str | None,
    kind: str | UsageKind | None,
    prompt_tokens: int,
    completion_tokens: int = 0,
    provider: str | None = None,
    execution: RunExecutionContext | None = None,
    call_id: str | None = None,
) -> UsageReceipt:
    """Record an incurred call when the consumer cannot receive provider usage.

    This seam is intentionally explicit: callers may use it only after a request was
    accepted and then interrupted by their own deadline/transport boundary.  Provider
    failover attempts rejected before acceptance must not create chargeable receipts.
    """

    from service.domain.usage_ledger import receipt_from_usage

    receipt = receipt_from_usage(
        {
            "prompt": max(0, int(prompt_tokens)),
            "completion": max(0, int(completion_tokens)),
        },
        provider=provider,
        model=model,
        kind=kind,
        receipt_id=call_id,
        estimated=True,
    )
    execution = require_execution(execution)
    execution.usage.record(receipt)
    return receipt


__all__ = ["invoke_model_call", "record_estimated_model_call"]
