"""Best-effort scan outcomes; labels never contain file or owner identity."""

import logging
from typing import Any

logger = logging.getLogger(__name__)
_OUTCOMES = frozenset({"succeeded", "failed", "skipped", "cancelled", "unknown"})


class FileScanMetrics:
    def __init__(self, *, registry: Any = None) -> None:
        self.outcome_total: Any = None
        try:
            from prometheus_client import Counter

            options = {} if registry is None else {"registry": registry}
            self.outcome_total = Counter(
                "file_scan_total",
                "Metadata scan outcomes; not antivirus certification",
                ["outcome"],
                **options,
            )
        except Exception:
            logger.debug("File scan metric unavailable", extra={"component": "file_scan"})

    def record(self, outcome: object) -> None:
        if self.outcome_total is None:
            return
        bounded = outcome if isinstance(outcome, str) and outcome in _OUTCOMES else "unknown"
        try:
            self.outcome_total.labels(outcome=bounded).inc()
        except Exception:
            logger.debug("File scan metric update unavailable", extra={"component": "file_scan"})


file_scan_metrics = FileScanMetrics()
