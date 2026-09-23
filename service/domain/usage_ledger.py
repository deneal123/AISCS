"""Run-scoped, receipt-based accounting for every LLM call."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from uuid import uuid4

USAGE_INTEGRITY_REASONS = frozenset({"missing_model", "missing_provider"})


class UsageKind(StrEnum):
    CHAT = "chat"
    ROUTE_MODEL = "route_model"
    ROUTER = "route_model"
    META = "meta_usage"
    MULTIMODAL = "multimodal_usage"
    IMAGE_CONDENSE = "image_condense_usage"
    PPTX_ILLUSTRATION = "pptx_illustration_usage"
    PDF_AUTHORING = "pdf_authoring"
    DOCUMENT_VISUAL_AUDIT = "document_visual_audit"
    TOOL_SELECTOR = "tool_selector"
    QUERY_RESOLUTION = "query_resolution"
    RESEARCH_PLAN = "research_plan"
    RESEARCH_SYNTHESIS = "research_synthesis"
    RESEARCH_REPAIR = "research_repair"
    AUDIO_POSTPROCESS = "audio_postprocess"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    TRANSLATION = "translation"
    MULTI_INTENT = "multi_intent_usage"
    EMPTY_RESPONSE = "empty_response_usage"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class UsageReceipt:
    """One logical provider call; unique within a run and never merged by model name."""

    receipt_id: str
    provider: str | None
    model: str | None
    prompt: int
    completion: int
    kind: str | None = None
    estimated: bool = False
    chargeable: bool = True

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    @property
    def billable(self) -> bool:
        # Missing provenance is an accounting anomaly, not permission to discard an
        # already incurred provider cost. Backend retains its existing default-price
        # fallback for a null model.
        return self.chargeable and self.total > 0

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "receipt_id": self.receipt_id,
            "model": self.model,
            "prompt": self.prompt,
            "completion": self.completion,
            "total": self.total,
        }
        if self.provider:
            data["provider"] = self.provider
        if self.kind:
            data["kind"] = self.kind
        if self.estimated:
            data["estimated"] = True
        return data


@dataclass(frozen=True, slots=True)
class UsageScope:
    """Immutable start position for projecting one logical execution stage."""

    start: int
    kind: str | None = None


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def receipt_from_usage(
    usage: Any,
    *,
    provider: str | None = None,
    model: str | None = None,
    kind: str | UsageKind | None = None,
    receipt_id: str | None = None,
    estimated: bool | None = None,
    chargeable: bool | None = None,
) -> UsageReceipt:
    mapping = usage if isinstance(usage, dict) else {}
    prompt = _non_negative_int(mapping.get("prompt", mapping.get("prompt_tokens", 0)))
    completion = _non_negative_int(mapping.get("completion", mapping.get("completion_tokens", 0)))
    return UsageReceipt(
        receipt_id=str(receipt_id or mapping.get("receipt_id") or uuid4().hex),
        provider=str(provider or mapping.get("provider") or "") or None,
        model=str(model or mapping.get("model") or "") or None,
        prompt=prompt,
        completion=completion,
        kind=str(kind or mapping.get("kind") or "") or None,
        estimated=bool(mapping.get("estimated", False) if estimated is None else estimated),
        chargeable=bool(mapping.get("chargeable", True) if chargeable is None else chargeable),
    )


def receipt_from_response(
    response: Any,
    *,
    provider: str | None,
    model: str | None,
    kind: str | UsageKind | None,
    receipt_id: str | None = None,
    chargeable: bool = True,
) -> UsageReceipt:
    usage = getattr(response, "usage", None)
    if usage is None:
        return receipt_from_usage(
            {},
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=receipt_id,
            chargeable=chargeable,
        )
    return receipt_from_usage(
        {
            "prompt": getattr(usage, "prompt_tokens", 0),
            "completion": getattr(usage, "completion_tokens", 0),
        },
        provider=provider,
        model=model,
        kind=kind,
        receipt_id=receipt_id,
        chargeable=chargeable,
    )


@dataclass(slots=True)
class UsageLedger:
    """Idempotent collection of exact call receipts."""

    _receipts: list[UsageReceipt] = field(default_factory=list)
    _ids: set[str] = field(default_factory=set)

    def record(self, receipt: UsageReceipt) -> bool:
        if receipt.receipt_id in self._ids:
            # Streaming providers may publish the accepted round before they publish
            # usage.  The zero-valued placeholder and the later exact/estimated receipt
            # are the same call, not two billable calls.
            for index, current in enumerate(self._receipts):
                if current.receipt_id != receipt.receipt_id:
                    continue
                if current.total == 0 and receipt.total > 0:
                    self._receipts[index] = receipt
                    return True
                return False
            return False
        self._ids.add(receipt.receipt_id)
        self._receipts.append(receipt)
        return True

    def record_usage(
        self,
        usage: Any,
        *,
        provider: str | None = None,
        model: str | None = None,
        kind: str | UsageKind | None = None,
        receipt_id: str | None = None,
        estimated: bool | None = None,
        chargeable: bool | None = None,
    ) -> UsageReceipt:
        receipt = receipt_from_usage(
            usage,
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=receipt_id,
            estimated=estimated,
            chargeable=chargeable,
        )
        self.record(receipt)
        return receipt

    def record_response(
        self,
        response: Any,
        *,
        provider: str | None,
        model: str | None,
        kind: str | UsageKind | None,
        receipt_id: str | None = None,
        chargeable: bool = True,
    ) -> UsageReceipt:
        receipt = receipt_from_response(
            response,
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=receipt_id,
            chargeable=chargeable,
        )
        self.record(receipt)
        return receipt

    def extend(self, receipts: Iterable[UsageReceipt]) -> None:
        for receipt in receipts:
            self.record(receipt)

    def set_chargeable(self, receipt_id: str, chargeable: bool = True) -> UsageReceipt | None:
        """Change only the charging decision for an already recorded immutable call."""

        for index, receipt in enumerate(self._receipts):
            if receipt.receipt_id != receipt_id:
                continue
            updated = replace(receipt, chargeable=bool(chargeable))
            self._receipts[index] = updated
            return updated
        return None

    @property
    def receipts(self) -> tuple[UsageReceipt, ...]:
        return tuple(self._receipts)

    def cursor(self) -> int:
        """Return a stable run-local position for later compatibility projection."""

        return len(self._receipts)

    def open_scope(self, *, kind: str | UsageKind | None = None) -> UsageScope:
        return UsageScope(
            start=len(self._receipts),
            kind=str(kind) if kind is not None else None,
        )

    def project_scope(self, scope: UsageScope) -> dict[str, Any]:
        if scope.kind is not None:
            return self.project_kind_range(scope.start, len(self._receipts), scope.kind)
        return self.project_range(scope.start, len(self._receipts))

    def project_kind_range(
        self,
        cursor: int,
        end: int | None,
        kind: str | UsageKind | None,
    ) -> dict[str, Any]:
        """Project one closed usage kind from an immutable ledger interval."""

        expected = str(kind) if kind is not None else None
        start = max(0, min(int(cursor), len(self._receipts)))
        stop = (
            len(self._receipts) if end is None else max(start, min(int(end), len(self._receipts)))
        )
        receipts = tuple(
            item for item in self._receipts[start:stop] if item.billable and item.kind == expected
        )
        return self._project_receipts(receipts)

    def record_fixed_equivalent(
        self,
        *,
        model: str,
        tokens: int,
        kind: str | UsageKind,
        provider: str | None = None,
        receipt_id: str | None = None,
    ) -> UsageReceipt:
        """Record a provider-priced fixed equivalent without a mutable accumulator."""

        return self.record_usage(
            {"prompt": max(0, int(tokens)), "completion": 0},
            provider=provider,
            model=model,
            kind=kind,
            receipt_id=receipt_id,
            estimated=True,
            chargeable=True,
        )

    def receipts_since(self, cursor: int) -> tuple[UsageReceipt, ...]:
        """Return receipts appended after ``cursor`` without exposing mutable storage."""

        start = max(0, min(int(cursor), len(self._receipts)))
        return tuple(self._receipts[start:])

    def project_since(self, cursor: int, *, kind: str | None = None) -> dict[str, Any]:
        """Build the historical envelope from calls already present in the ledger."""

        return self.project_range(cursor, None, kind=kind)

    def project_range(
        self, cursor: int, end: int | None, *, kind: str | None = None
    ) -> dict[str, Any]:
        """Project a bounded receipt interval without mutating accounting state."""

        receipts = self.receipts_since(cursor)
        if end is not None:
            width = max(0, int(end) - max(0, int(cursor)))
            receipts = receipts[:width]
        receipts = tuple(
            item for item in receipts if item.billable and (kind is None or item.kind == str(kind))
        )
        prompt = sum(item.prompt for item in receipts)
        completion = sum(item.completion for item in receipts)
        data: dict[str, Any] = {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
            "calls": [item.as_dict() for item in receipts],
        }
        if kind:
            data["kind"] = kind
        if len(receipts) == 1:
            receipt = receipts[0]
            data["model"] = receipt.model
            if receipt.provider:
                data["provider"] = receipt.provider
            if receipt.estimated:
                data["estimated"] = True
        return data

    def project_kind_since(self, cursor: int, kind: str | UsageKind | None) -> dict[str, Any]:
        """Project only calls of one kind from a run-local interval."""

        return self.project_kind_range(cursor, None, kind)

    @staticmethod
    def _project_receipts(receipts: tuple[UsageReceipt, ...]) -> dict[str, Any]:
        prompt = sum(item.prompt for item in receipts)
        completion = sum(item.completion for item in receipts)
        data: dict[str, Any] = {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
            "calls": [item.as_dict() for item in receipts],
        }
        models = {item.model for item in receipts if item.model}
        providers = {item.provider for item in receipts if item.provider}
        if len(models) == 1:
            data["model"] = next(iter(models))
        if len(providers) == 1:
            data["provider"] = next(iter(providers))
        if receipts and any(item.estimated for item in receipts):
            data["estimated"] = True
        return data

    def project_kinds_since(
        self, cursor: int, kinds: Iterable[str | UsageKind | None]
    ) -> dict[str, Any]:
        """Project a closed set of usage kinds from a run-local interval."""

        expected = {str(kind) if kind is not None else None for kind in kinds}
        receipts = tuple(
            item for item in self.receipts_since(cursor) if item.billable and item.kind in expected
        )
        prompt = sum(item.prompt for item in receipts)
        completion = sum(item.completion for item in receipts)
        data: dict[str, Any] = {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
            "calls": [item.as_dict() for item in receipts],
        }
        models = {item.model for item in receipts if item.model}
        providers = {item.provider for item in receipts if item.provider}
        if len(models) == 1:
            data["model"] = next(iter(models))
        if len(providers) == 1:
            data["provider"] = next(iter(providers))
        if receipts and any(item.estimated for item in receipts):
            data["estimated"] = True
        return data

    def get(self, receipt_id: str | None) -> UsageReceipt | None:
        if not receipt_id:
            return None
        return next((item for item in self._receipts if item.receipt_id == receipt_id), None)

    def has_kind(self, kind: str) -> bool:
        return any(item.kind == kind for item in self._receipts)

    @property
    def prompt_tokens(self) -> int:
        return sum(item.prompt for item in self._receipts if item.billable)

    @property
    def completion_tokens(self) -> int:
        return sum(item.completion for item in self._receipts if item.billable)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def billable_calls(self) -> int:
        return sum(1 for item in self._receipts if item.billable)

    def anomaly_counts(self) -> dict[str, int]:
        """Bounded provenance gaps without dropping already incurred usage."""

        counts = {
            "missing_provider": sum(1 for item in self._receipts if not item.provider),
            "missing_model": sum(1 for item in self._receipts if not item.model),
        }
        if frozenset(counts) != USAGE_INTEGRITY_REASONS:
            raise RuntimeError("usage integrity taxonomy mismatch")
        return {name: count for name, count in counts.items() if count}

    def as_token_usage(self, *, kind: str | None = None) -> dict[str, Any]:
        """Compatibility aggregate carrying exact per-call receipts alongside totals."""

        data: dict[str, Any] = {
            "prompt": self.prompt_tokens,
            "completion": self.completion_tokens,
            "total": self.total_tokens,
            "calls": [item.as_dict() for item in self._receipts if item.billable],
        }
        if kind:
            data["kind"] = kind
        if anomalies := self.anomaly_counts():
            data["usage_anomalies"] = anomalies
        return data

    def bounded_summary(self) -> dict[str, int]:
        summary = {
            "call_count": len(self._receipts),
            "billable_call_count": self.billable_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }
        summary["anomaly_count"] = sum(self.anomaly_counts().values())
        return summary


__all__ = [
    "USAGE_INTEGRITY_REASONS",
    "UsageKind",
    "UsageLedger",
    "UsageReceipt",
    "UsageScope",
    "receipt_from_response",
    "receipt_from_usage",
]
