from __future__ import annotations

from datetime import date


def month_period(today: date) -> tuple[date, date]:
    """Return the half-open current calendar-month period."""
    start = today.replace(day=1)
    if start.month == 12:
        return start, date(start.year + 1, 1, 1)
    return start, date(start.year, start.month + 1, 1)
