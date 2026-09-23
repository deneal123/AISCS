from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from service.services.billing.application.cost_guard_metrics import cost_guard_metrics


def cost_guard_status(
    *,
    healthy: bool,
    fallback_pricing: int,
    prompt_budget_stops: int,
    expired: int,
    warning_events: int = 1,
    critical_events: int = 5,
) -> dict[str, str]:
    if not healthy:
        return {
            "level": "critical",
            "next_action": "Проверьте цены и маржу до новых дорогих запусков.",
        }
    if expired > 0:
        return {
            "level": "critical",
            "next_action": "Очистите просроченные резервы и проверьте worker.",
        }
    events = fallback_pricing + prompt_budget_stops
    if events >= max(int(critical_events), int(warning_events), 1):
        return {
            "level": "critical",
            "next_action": "Остановите дорогие запуски и исправьте fallback-цены или budget-stop.",
        }
    if events >= max(int(warning_events), 1):
        return {
            "level": "warning",
            "next_action": "Проверьте fallback-цены и разбейте дорогие запуски.",
        }
    return {"level": "normal", "next_action": "Действий не требуется."}


async def cleanup_expired_reservations(repo: Any) -> dict[str, int]:
    cleanup = getattr(repo, "cleanup_expired_reservations", None)
    snapshot = getattr(repo, "fetch_reservation_snapshot", None)
    expired = int(await cleanup()) if cleanup is not None else 0
    for _ in range(expired):
        cost_guard_metrics.reservation("expired")
    state = await snapshot() if snapshot is not None else {"active": 0, "expired": 0}
    cost_guard_metrics.reservation_snapshot(
        active=int(state.get("active", 0)), expired=int(state.get("expired", 0))
    )
    return {"expired": expired, **state}


def record_charge_observability(
    *, reservation_id: str | None, result: dict[str, Any], metadata: dict[str, Any] | None
) -> None:
    if reservation_id and not result.get("idempotent"):
        cost_guard_metrics.reservation("committed")
    metadata = metadata or {}
    if metadata.get("billing_fallback"):
        cost_guard_metrics.pricing_fallback(metadata.get("provider"), metadata["billing_fallback"])
    if metadata.get("stop_reason") == "prompt_budget_reached":
        cost_guard_metrics.prompt_budget_stop(metadata.get("provider"))


async def add_cost_guard_snapshot(
    *, repo: Any, result: dict[str, Any], warning_events: int = 1, critical_events: int = 5
) -> None:
    now = datetime.now(UTC)
    events_fetch = getattr(repo, "fetch_cost_guard_events", None)
    snapshot_fetch = getattr(repo, "fetch_reservation_snapshot", None)
    events = await events_fetch(since=now - timedelta(hours=24)) if events_fetch else {}
    reservations = await snapshot_fetch() if snapshot_fetch else {"active": 0, "expired": 0}
    result["cost_guard"] = {
        "window": "24h",
        "raw_cost_rub": round(float(events.get("raw_cost_rub", 0)), 4),
        "fallback_pricing": int(events.get("fallback_pricing", 0)),
        "prompt_budget_stops": int(events.get("prompt_budget_stops", 0)),
        "active_reservations": int(reservations.get("active", 0)),
        "expired_reservations": int(reservations.get("expired", 0)),
        "last_successful_reconcile_at": now.isoformat(),
        "freshness_seconds": 0,
    }
    result["status"] = cost_guard_status(
        healthy=bool(result["healthy"]),
        fallback_pricing=result["cost_guard"]["fallback_pricing"],
        prompt_budget_stops=result["cost_guard"]["prompt_budget_stops"],
        expired=result["cost_guard"]["expired_reservations"],
        warning_events=warning_events,
        critical_events=critical_events,
    )
    cost_guard_metrics.reservation_snapshot(
        active=result["cost_guard"]["active_reservations"],
        expired=result["cost_guard"]["expired_reservations"],
    )
    cost_guard_metrics.reconciliation_succeeded(now.timestamp())
