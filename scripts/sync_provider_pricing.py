"""Fetch current RouterAI/OpenRouter catalogs and emit transactional SQL.

Usage (from backend):
    uv run --frozen python scripts/sync_provider_pricing.py | docker exec -i ... psql ...

The runtime Celery task and this manual tool share the same catalog validation.
"""

from __future__ import annotations

import sys
from decimal import Decimal

from service.services.billing.application.provider_catalog import fetch_provider_pricing_catalogs


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _emit(provider: str, rows: list[tuple[str, Decimal, Decimal]], source: str) -> None:
    """Emit one provider's refresh without overwriting an admin override."""
    delete_sql = (
        "DELETE FROM profile.model_pricing WHERE provider = "
        f"{_sql_quote(provider)} AND (updated_by = 'routerai-seed' "
        f"OR updated_by LIKE 'sync:{provider}:%');"
    )
    print(delete_sql)
    for model_id, price_in, price_out in rows:
        print(
            "INSERT INTO profile.model_pricing "
            "(provider, model_id, price_in_rub_per_1k, price_out_rub_per_1k, "
            "model_class, updated_by, updated_at) VALUES "
            f"({_sql_quote(provider)}, {_sql_quote(model_id)}, {price_in:.10f}, "
            f"{price_out:.10f}, NULL, {_sql_quote(source)}, now()) "
            "ON CONFLICT (provider, model_id) DO UPDATE SET "
            "price_in_rub_per_1k = EXCLUDED.price_in_rub_per_1k, "
            "price_out_rub_per_1k = EXCLUDED.price_out_rub_per_1k, "
            "updated_by = EXCLUDED.updated_by, updated_at = now()"
            " WHERE profile.model_pricing.updated_by IS NULL "
            "OR profile.model_pricing.updated_by = 'routerai-seed' "
            f"OR profile.model_pricing.updated_by LIKE 'sync:{provider}:%';"
        )


def main() -> int:
    catalogs = fetch_provider_pricing_catalogs()
    print("BEGIN;")
    for catalog in catalogs:
        _emit(catalog.provider, catalog.rows, catalog.source)
    print("COMMIT;")
    print(
        "-- "
        + "; ".join(
            f"{catalog.provider}: {len(catalog.rows)} priced models" for catalog in catalogs
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
