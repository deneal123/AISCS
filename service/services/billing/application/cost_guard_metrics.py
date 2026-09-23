"""Bounded Prometheus metrics for billing safeguards."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_PROVIDERS = {"gigachat", "openrouter", "routerai", "unknown"}
_REASONS = {
    "prompt_budget_reached",
    "per_call_reconstructed",
    "no_provider_usage_floor",
    "model_substitution_capped",
    "pricing_failed_floor",
    "pricing_failed_zero",
    "unknown",
}


def _provider(value: str | None) -> str:
    value = str(value or "unknown").lower()
    return value if value in _PROVIDERS else "unknown"


def _reason(value: str | None) -> str:
    value = str(value or "unknown")
    return value if value in _REASONS else "unknown"


class CostGuardMetrics:
    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge

            self.prompt_budget_stops = Counter(
                "billing_prompt_budget_stops_total",
                "Chat runs stopped by per-run prompt budget",
                ["provider", "reason"],
            )
            self.pricing_fallbacks = Counter(
                "billing_pricing_fallbacks_total",
                "Usage charges with pricing fallback",
                ["provider", "reason"],
            )
            self.reservation_events = Counter(
                "billing_reservation_events_total", "Reservation lifecycle events", ["outcome"]
            )
            self.reservations_active = Gauge(
                "billing_reservations_active", "Currently active credit reservations"
            )
            self.reservations_expired = Gauge(
                "billing_reservations_expired", "Expired reservations awaiting cleanup"
            )
            self.reconcile_last_success = Gauge(
                "billing_reconcile_last_success_timestamp_seconds",
                "Last successful billing reconciliation",
            )
            self.provider_health = Gauge(
                "billing_provider_health", "Provider health state", ["provider", "status"]
            )
        except Exception:  # pragma: no cover
            logger.debug("Prometheus billing metrics unavailable", exc_info=True)
            self.prompt_budget_stops = self.pricing_fallbacks = self.reservation_events = None
            self.reservations_active = self.reservations_expired = None
            self.reconcile_last_success = self.provider_health = None

    def prompt_budget_stop(self, provider: str | None) -> None:
        self._inc(
            self.prompt_budget_stops, provider=_provider(provider), reason="prompt_budget_reached"
        )

    def pricing_fallback(self, provider: str | None, reason: str | None) -> None:
        self._inc(self.pricing_fallbacks, provider=_provider(provider), reason=_reason(reason))

    def reservation(self, outcome: str) -> None:
        self._inc(
            self.reservation_events,
            outcome=outcome
            if outcome in {"created", "committed", "released", "expired"}
            else "released",
        )

    def reservation_snapshot(self, *, active: int, expired: int) -> None:
        self._set(self.reservations_active, active)
        self._set(self.reservations_expired, expired)

    def reconciliation_succeeded(self, timestamp: float) -> None:
        self._set(self.reconcile_last_success, timestamp)

    def provider(self, name: str | None, status: str) -> None:
        metric = self.provider_health
        if metric is None:
            return
        status = status if status in {"normal", "warning", "critical"} else "warning"
        try:
            for candidate in ("normal", "warning", "critical"):
                metric.labels(provider=_provider(name), status=candidate).set(candidate == status)
        except Exception:
            logger.debug("Failed to set provider metric", exc_info=True)

    @staticmethod
    def _inc(metric, **labels) -> None:
        if metric is not None:
            try:
                metric.labels(**labels).inc()
            except Exception:
                logger.debug("Failed to increment billing metric", exc_info=True)

    @staticmethod
    def _set(metric, value: int | float) -> None:
        if metric is not None:
            try:
                metric.set(value)
            except Exception:
                logger.debug("Failed to set billing metric", exc_info=True)


cost_guard_metrics = CostGuardMetrics()
