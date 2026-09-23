"""Bounded operational metrics for autonomous workflow catalog maintenance."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WorkflowCatalogMetrics:
    def __init__(self) -> None:
        try:
            from prometheus_client import Counter, Gauge

            self.delivery_total = Counter(
                "workflow_catalog_outbox_delivery_total",
                "Workflow catalog outbox projection outcomes",
                ["status", "error_class"],
            )
            self.maintenance_total = Counter(
                "workflow_catalog_maintenance_total",
                "Workflow catalog hourly maintenance outcomes",
                ["status"],
            )
            self.outbox_depth = Gauge(
                "workflow_catalog_outbox_depth",
                "Undelivered workflow catalog outbox rows",
            )
            self.outbox_oldest_age_seconds = Gauge(
                "workflow_catalog_outbox_oldest_age_seconds",
                "Age of the oldest undelivered workflow catalog outbox row",
            )
        except Exception:  # pragma: no cover - Prometheus is optional locally
            logger.debug("Workflow catalog metrics unavailable", exc_info=True)
            self.delivery_total = self.maintenance_total = None
            self.outbox_depth = self.outbox_oldest_age_seconds = None

    def delivery(self, delivered: bool, error_class: str = "") -> None:
        if self.delivery_total is None:
            return
        status = "delivered" if delivered else "deferred"
        safe_error = (
            error_class if error_class in {"transport", "timeout", "protocol", "remote"} else "none"
        )
        try:
            self.delivery_total.labels(status=status, error_class=safe_error).inc()
        except Exception:
            logger.debug("Failed to record catalog delivery metric", exc_info=True)

    def snapshot(self, *, depth: int, oldest_age_sec: int) -> None:
        try:
            if self.outbox_depth is not None:
                self.outbox_depth.set(max(0, depth))
            if self.outbox_oldest_age_seconds is not None:
                self.outbox_oldest_age_seconds.set(max(0, oldest_age_sec))
        except Exception:
            logger.debug("Failed to record catalog queue metrics", exc_info=True)

    def maintenance(self, status: str) -> None:
        if self.maintenance_total is None:
            return
        try:
            self.maintenance_total.labels(
                status="success" if status == "success" else "error"
            ).inc()
        except Exception:
            logger.debug("Failed to record catalog maintenance metric", exc_info=True)


catalog_metrics = WorkflowCatalogMetrics()
