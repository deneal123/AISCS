"""Run-scoped provider session: pinning, private state, call IDs, and receipts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from uuid import uuid4

from service.domain.usage_ledger import UsageKind, UsageLedger, UsageReceipt

from .failures import ProviderFailure, classify_provider_failure


class PinSource(StrEnum):
    NON_STREAM_RESPONSE = "non_stream_response"
    STREAM_DELTA = "stream_delta"


@dataclass(frozen=True, slots=True)
class ProviderRoundReceipt:
    round_index: int
    provider: str
    model: str
    call_id: str
    usage_receipt_id: str | None
    finish_reason: str | None
    pin_source: PinSource

    def bounded_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "round": self.round_index,
            "provider": self.provider,
            "model": self.model,
            "pin_source": self.pin_source.value,
        }
        if self.finish_reason:
            data["finish_reason"] = self.finish_reason
        return data


@dataclass(slots=True)
class ProviderRunSession:
    """State shared by all model rounds of one agents run.

    Opaque provider state is stored separately from canonical messages.  The session can
    project it into a provider payload but never exposes it through events or metadata.
    """

    run_id: str = field(default_factory=lambda: uuid4().hex)
    usage: UsageLedger = field(default_factory=UsageLedger)
    pinned_provider: str | None = None
    pinned_model: str | None = None
    _private_state: dict[str, str] = field(default_factory=dict)
    _rounds: list[ProviderRoundReceipt] = field(default_factory=list)
    _call_sequence: int = 0
    _active_round_index: int | None = None

    def provider_order(self, candidates: list[str]) -> list[str]:
        if self.pinned_provider:
            return [self.pinned_provider] if self.pinned_provider in candidates else []
        return list(candidates)

    def assert_provider(self, provider: str) -> None:
        if self.pinned_provider and provider != self.pinned_provider:
            raise RuntimeError("provider_pinning")

    def pin(
        self,
        provider: str,
        model: str,
        *,
        source: PinSource,
    ) -> None:
        if self.pinned_provider is None:
            self.pinned_provider = provider
            self.pinned_model = model
            return
        if provider != self.pinned_provider or model != self.pinned_model:
            raise RuntimeError("provider_pinning")

    def next_call_id(self, *, provider: str | None = None) -> str:
        """Generate a unique, opaque ID suitable for canonical tool history."""

        self._call_sequence += 1
        prefix = "call"
        if provider:
            safe = "".join(char for char in provider.lower() if char.isalnum())[:12]
            if safe:
                prefix = f"call_{safe}"
        return f"{prefix}_{self.run_id[:12]}_{self._call_sequence}"

    def set_private_state(self, provider: str, state: Any) -> None:
        if not isinstance(state, str):
            return
        value = state.strip()
        if value:
            self._private_state[provider] = value[:2048]

    def private_state(self, provider: str) -> str | None:
        return self._private_state.get(provider)

    def clear_private_state(self, provider: str) -> None:
        self._private_state.pop(provider, None)

    def complete_round(
        self,
        *,
        provider: str,
        model: str,
        response: Any = None,
        usage: Any = None,
        finish_reason: str | None = None,
        source: PinSource = PinSource.NON_STREAM_RESPONSE,
        kind: str | UsageKind | None = UsageKind.CHAT,
        call_id: str | None = None,
        estimated: bool | None = None,
    ) -> ProviderRoundReceipt:
        self.accept_round(
            provider=provider,
            model=model,
            source=source,
            kind=kind,
            call_id=call_id,
        )
        return self.complete_accepted(
            response=response,
            usage=usage,
            finish_reason=finish_reason,
            kind=kind,
            estimated=(
                bool(usage.get("estimated"))
                if estimated is None and isinstance(usage, dict)
                else bool(estimated)
            ),
        )

    def accept_round(
        self,
        *,
        provider: str,
        model: str,
        source: PinSource,
        kind: str | UsageKind | None = UsageKind.CHAT,
        call_id: str | None = None,
    ) -> ProviderRoundReceipt:
        """Pin and reserve exactly one call identity on first accepted output."""

        self.pin(provider, model, source=source)
        if self._active_round_index is not None:
            return self._rounds[self._active_round_index]
        resolved_call_id = call_id or self.next_call_id(provider=provider)
        placeholder = self.usage.record_usage(
            {},
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=resolved_call_id,
        )
        receipt = ProviderRoundReceipt(
            round_index=len(self._rounds),
            provider=provider,
            model=model,
            call_id=resolved_call_id,
            usage_receipt_id=placeholder.receipt_id,
            finish_reason=None,
            pin_source=source,
        )
        self._rounds.append(receipt)
        self._active_round_index = receipt.round_index
        return receipt

    def complete_accepted(
        self,
        *,
        response: Any = None,
        usage: Any = None,
        finish_reason: str | None = None,
        kind: str | UsageKind | None = None,
        estimated: bool = False,
    ) -> ProviderRoundReceipt:
        """Attach exact/estimated usage to the currently accepted call and close it."""

        if self._active_round_index is None:
            raise RuntimeError("provider_protocol")
        index = self._active_round_index
        accepted = self._rounds[index]
        existing = self.usage.get(accepted.usage_receipt_id)
        resolved_kind = (
            kind if kind is not None else (existing.kind if existing is not None else None)
        )
        usage_receipt: UsageReceipt | None = None
        if response is not None:
            usage_receipt = self.usage.record_response(
                response,
                provider=accepted.provider,
                model=accepted.model,
                kind=resolved_kind,
                receipt_id=accepted.call_id,
            )
        elif usage is not None:
            usage_receipt = self.usage.record_usage(
                usage,
                provider=accepted.provider,
                model=accepted.model,
                kind=resolved_kind,
                receipt_id=accepted.call_id,
                estimated=estimated,
            )
        receipt = replace(
            accepted,
            usage_receipt_id=(
                usage_receipt.receipt_id if usage_receipt is not None else accepted.usage_receipt_id
            ),
            finish_reason=finish_reason,
        )
        self._rounds[index] = receipt
        self._active_round_index = None
        return receipt

    def interrupt_accepted(
        self,
        usage: Any,
        *,
        estimated: bool = True,
    ) -> ProviderRoundReceipt:
        """Close an accepted interrupted call under its original identity.

        Some providers emit exact usage before the transport terminates. The caller
        can retain that usage instead of downgrading it to an estimate.
        """

        return self.complete_accepted(usage=usage, estimated=estimated)

    def record_round_usage(
        self,
        usage: Any,
        *,
        round_index: int = -1,
        estimated: bool = False,
    ) -> UsageReceipt | None:
        """Fill usage for an already accepted round without creating another call."""

        if not self._rounds:
            return None
        try:
            round_receipt = self._rounds[round_index]
        except IndexError:
            return None
        existing = self.usage.get(round_receipt.usage_receipt_id)
        receipt = self.usage.record_usage(
            usage,
            provider=round_receipt.provider,
            model=round_receipt.model,
            kind=existing.kind if existing is not None else None,
            receipt_id=round_receipt.call_id,
            estimated=estimated,
        )
        if round_receipt.usage_receipt_id is None:
            actual_index = round_index if round_index >= 0 else len(self._rounds) + round_index
            self._rounds[actual_index] = replace(
                round_receipt,
                usage_receipt_id=receipt.receipt_id,
            )
        return self.usage.get(receipt.receipt_id)

    def failure(self, exc: BaseException, *, provider: str | None = None) -> ProviderFailure:
        return classify_provider_failure(exc, provider=provider)

    @property
    def rounds(self) -> tuple[ProviderRoundReceipt, ...]:
        return tuple(self._rounds)

    @property
    def round_count(self) -> int:
        return len(self._rounds)

    @property
    def has_active_round(self) -> bool:
        return self._active_round_index is not None

    def bounded_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "round_count": self.round_count,
            **self.usage.bounded_summary(),
        }
        if self.pinned_provider:
            data["provider"] = self.pinned_provider
        if self.pinned_model:
            data["model"] = self.pinned_model
        return data


__all__ = ["PinSource", "ProviderRoundReceipt", "ProviderRunSession"]
