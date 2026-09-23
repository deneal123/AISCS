"""Typed provider-round adapter for the streamed chat runner."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

from service.domain.client.protocol import (
    PinSource,
    ProviderRoundReceipt,
    ProviderRoundState,
    ProviderRunSession,
    ProviderStreamEvent,
)
from service.domain.usage_ledger import UsageReceipt, receipt_from_usage
from service.shared.token_budget import estimate_tokens


def _estimated_round_usage(
    messages: list[dict], tools: list[dict] | None, pieces: list[str]
) -> dict[str, Any]:
    prompt = estimate_tokens(json.dumps(messages, ensure_ascii=False, default=str))
    prompt += estimate_tokens(json.dumps(tools or [], ensure_ascii=False, default=str))
    return {
        "prompt": prompt,
        "completion": estimate_tokens("".join(pieces)),
        "estimated": True,
    }


def _complete_usage(
    state: ProviderRoundState,
    *,
    messages: list[dict],
    tools: list[dict] | None,
    pieces: list[str],
) -> dict[str, Any]:
    usage = state.usage()
    estimated = _estimated_round_usage(messages, tools, pieces)
    missing_prompt = not int(usage.get("prompt") or 0)
    missing_completion = not int(usage.get("completion") or 0)
    if missing_prompt:
        usage["prompt"] = estimated["prompt"]
    if missing_completion:
        usage["completion"] = estimated["completion"]
    usage["total"] = int(usage.get("total") or 0) or (
        int(usage.get("prompt") or 0) + int(usage.get("completion") or 0)
    )
    if missing_prompt or missing_completion:
        usage["estimated"] = True
    return usage


def _accept_untracked_delta(
    session: ProviderRunSession,
    state: ProviderRoundState,
    *,
    rounds_before: int,
    pin_provider: str | None,
    model: str,
) -> None:
    if session.round_count != rounds_before or session.has_active_round:
        return
    session.accept_round(
        provider=str(state.provider or session.pinned_provider or pin_provider or "unknown"),
        model=str(state.model or session.pinned_model or model),
        source=PinSource.STREAM_DELTA,
    )


def _interrupt_round(
    session: ProviderRunSession,
    state: ProviderRoundState,
    *,
    messages: list[dict],
    tools: list[dict] | None,
    pieces: list[str],
    rounds_before: int,
    model: str,
) -> None:
    has_exact_usage = bool(state.prompt or state.completion or state.total)
    usage = state.usage() if has_exact_usage else _estimated_round_usage(messages, tools, pieces)
    if session.has_active_round:
        session.interrupt_accepted(usage, estimated=not has_exact_usage)
        return
    if session.round_count == rounds_before and session.pinned_provider:
        session.complete_round(
            provider=session.pinned_provider,
            model=session.pinned_model or model,
            usage=usage,
            source=PinSource.STREAM_DELTA,
            estimated=not has_exact_usage,
        )


def _finish_round(
    session: ProviderRunSession,
    state: ProviderRoundState,
    *,
    messages: list[dict],
    tools: list[dict] | None,
    pieces: list[str],
    rounds_before: int,
    pin_provider: str | None,
    model: str,
) -> tuple[ProviderRoundReceipt, UsageReceipt]:
    usage = _complete_usage(state, messages=messages, tools=tools, pieces=pieces)
    if session.has_active_round:
        round_receipt = session.complete_accepted(
            usage=usage,
            finish_reason=state.finish_reason,
            estimated=bool(usage.get("estimated")),
        )
    elif session.round_count == rounds_before:
        round_receipt = session.complete_round(
            provider=str(state.provider or session.pinned_provider or pin_provider or "unknown"),
            model=str(state.model or model),
            usage=usage,
            finish_reason=state.finish_reason,
            source=PinSource.NON_STREAM_RESPONSE,
        )
    else:
        round_receipt = session.rounds[-1]
        existing = session.usage.get(round_receipt.usage_receipt_id)
        if existing is None or existing.total <= 0:
            session.record_round_usage(usage, estimated=bool(usage.get("estimated")))

    usage_receipt = session.usage.get(round_receipt.usage_receipt_id)
    if usage_receipt is None:
        usage_receipt = receipt_from_usage(
            _estimated_round_usage(messages, tools, pieces),
            provider=round_receipt.provider,
            model=round_receipt.model,
            receipt_id=round_receipt.call_id,
            estimated=True,
        )
        session.usage.record(usage_receipt)
    return round_receipt, usage_receipt


async def provider_events(
    stream: Callable[..., AsyncGenerator[str]],
    *,
    messages: list[dict],
    model: str,
    max_tokens: int,
    tools: list[dict] | None,
    pin_provider: str | None,
    tool_choice: str | dict | None,
    provider_session: ProviderRunSession,
) -> AsyncGenerator[ProviderStreamEvent]:
    """Adapt one accepted provider stream into immutable round events.

    The public string-stream facade still projects its private SDK accumulator into a
    mapping. That mapping is contained here and is never shared with orchestration or
    billing; the owning session records one immutable receipt for the accepted round.
    """

    round_state = ProviderRoundState()
    pieces: list[str] = []
    rounds_before = provider_session.round_count
    try:
        async for delta in stream(
            messages=messages,
            model=model,
            temperature=0.7,
            max_tokens=max_tokens,
            tools=tools or None,
            tool_choice=tool_choice,
            pin_provider=pin_provider,
            provider_session=provider_session,
            round_state=round_state,
        ):
            pieces.append(delta)
            _accept_untracked_delta(
                provider_session,
                round_state,
                rounds_before=rounds_before,
                pin_provider=pin_provider,
                model=model,
            )
            yield ProviderStreamEvent.delta(delta)
    except BaseException:
        _interrupt_round(
            provider_session,
            round_state,
            messages=messages,
            tools=tools,
            pieces=pieces,
            rounds_before=rounds_before,
            model=model,
        )
        raise

    if reasoning := round_state.reasoning:
        yield ProviderStreamEvent.reasoning(
            str(reasoning),
            tokens=round_state.reasoning_tokens,
        )
    calls = round_state.tool_calls
    if isinstance(calls, list) and calls:
        yield ProviderStreamEvent.tool_calls_event(calls)

    round_receipt, usage_receipt = _finish_round(
        provider_session,
        round_state,
        messages=messages,
        tools=tools,
        pieces=pieces,
        rounds_before=rounds_before,
        pin_provider=pin_provider,
        model=model,
    )
    yield ProviderStreamEvent.completed(
        receipt=round_receipt,
        usage=usage_receipt,
        finish_reason=round_receipt.finish_reason,
    )


__all__ = ["provider_events"]
