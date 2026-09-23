"""Safety rails for the provider-catalog pricing import."""

from decimal import Decimal

import pytest

from scripts.sync_provider_pricing import _emit
from service.services.billing.application.provider_catalog import _rates, _validate_catalog


def test_rates_convert_token_prices_to_rub_per_thousand() -> None:
    rows = _rates(
        [
            {
                "id": "provider/model",
                "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            },
            {"id": "free", "pricing": {"prompt": "0", "completion": "0"}},
        ],
        usd_to_rub=Decimal("80"),
    )

    assert rows == [("provider/model", Decimal("0.080000"), Decimal("0.160000"))]


def test_catalog_sync_never_overwrites_admin_price(capsys) -> None:
    _emit(
        "openrouter",
        [("openai/model", Decimal("1"), Decimal("2"))],
        "sync:openrouter:2026-08-06",
    )

    output = capsys.readouterr().out
    assert "DELETE FROM profile.model_pricing WHERE provider = 'openrouter'" in output
    assert "updated_by LIKE 'sync:openrouter:%'" in output
    assert "ON CONFLICT (provider, model_id) DO UPDATE SET" in output
    assert "WHERE profile.model_pricing.updated_by IS NULL" in output
    assert "updated_by = 'routerai-seed'" in output


def test_catalog_import_refuses_an_incomplete_or_duplicate_catalog() -> None:
    rows = [(f"model-{number}", Decimal("1"), Decimal("2")) for number in range(100)]

    _validate_catalog("routerai", rows)
    with pytest.raises(RuntimeError, match="expected at least"):
        _validate_catalog("openrouter", rows[:99])
    with pytest.raises(RuntimeError, match="duplicate model ids"):
        _validate_catalog("routerai", [*rows[:-1], rows[0]])


def test_catalog_import_refuses_negative_provider_prices() -> None:
    with pytest.raises(ValueError, match="negative price"):
        _rates([{"id": "broken", "pricing": {"prompt": "-0.0001", "completion": "0"}}])


def test_catalog_import_skips_dynamic_router_sentinel() -> None:
    assert (
        _rates([{"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}}]) == []
    )
