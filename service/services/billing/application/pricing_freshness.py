"""Operator-facing freshness for provider price catalogs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_PROVIDER_POLICIES = {
    "routerai": (24 * 3600, 72 * 3600),
    "openrouter": (24 * 3600, 72 * 3600),
    "gigachat": (180 * 24 * 3600, 365 * 24 * 3600),
}


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def pricing_sync_status(
    rows: list[dict[str, Any]], *, now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Summarise only authoritative imports; manual edits do not mask staleness."""
    now = now or datetime.now(UTC)
    providers: list[dict[str, Any]] = []
    for provider, (normal_age, warning_age) in _PROVIDER_POLICIES.items():
        source_prefix = "system:gigachat-tariff" if provider == "gigachat" else f"sync:{provider}:"
        synced = [
            row
            for row in rows
            if str(row.get("provider") or "").lower() == provider
            and str(row.get("updated_by") or "").startswith(source_prefix)
        ]
        timestamps = [
            timestamp
            for row in synced
            if (timestamp := _as_datetime(row.get("updated_at"))) is not None
        ]
        latest = max(timestamps, default=None)
        age = max(0, int((now - latest).total_seconds())) if latest is not None else None
        if age is None or age > warning_age:
            level, action = "critical", "Обновите прайс-каталог и проверьте источник цен."
        elif age > normal_age:
            level, action = "warning", "Запланируйте обновление каталога в ближайшее время."
        else:
            level, action = "normal", "Каталог цен актуален."
        providers.append(
            {
                "provider": provider,
                "level": level,
                "next_action": action,
                "last_synced_at": latest.isoformat() if latest is not None else None,
                "freshness_seconds": age,
                "synced_models": len(synced),
            }
        )
    return {"providers": providers}
