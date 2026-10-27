"""Authenticated user-safe availability projection, not an administrative health API."""

from __future__ import annotations

import math
import re
from typing import Any

_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
_LABEL = re.compile(r"[A-Za-z0-9 ._-]{1,64}\Z")
_STATES = {"ready", "unavailable", "unknown", "disabled", "stale"}
_LOCAL_LABEL = "Локальная модель"


def project_provider_status(
    data: Any, disabled: set[str], blocked: set[str] | None = None
) -> dict[str, Any]:
    rows = []
    seen = set()
    raw = data.get("providers", []) if isinstance(data, dict) else []
    for item in raw[:32] if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name, label = item.get("id"), item.get("label")
        if not isinstance(name, str) or not _ID.fullmatch(name) or name in seen:
            continue
        if name == "local":
            label = _LOCAL_LABEL
        elif not isinstance(label, str) or not _LABEL.fullmatch(label):
            label = name
        seen.add(name)
        state = item.get("state")
        state = state if isinstance(state, str) and state in _STATES else "unknown"
        checked_at = item.get("checked_at")
        if type(checked_at) not in {int, float} or not math.isfinite(checked_at) or checked_at <= 0:
            checked_at = None
        rows.append(
            {
                "id": name,
                "label": label,
                "primary": item.get("primary") is True,
                "state": "disabled"
                if name in disabled
                else "unavailable"
                if name in (blocked or set())
                else state,
                "checked_at": checked_at,
            }
        )
    rows.sort(
        key=lambda row: (row["state"] == "disabled", not row["primary"], row["label"].lower())
    )
    eligible = [row for row in rows if row["state"] != "disabled"]
    ready = sum(row["state"] == "ready" for row in eligible)
    state = (
        "unknown"
        if not rows
        else "available"
        if ready and ready == len(eligible)
        else "degraded"
        if ready
        else "unknown"
        if any(row["state"] in {"unknown", "stale"} for row in eligible)
        else "unavailable"
    )
    return {"state": state, "ready": ready, "total": len(eligible), "providers": rows}
