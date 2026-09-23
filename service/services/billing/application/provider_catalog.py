"""Safe retrieval and normalization of provider price catalogs."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from urllib.request import Request, urlopen

ROUTERAI_MODELS_URL = "https://routerai.ru/api/v1/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CBR_DAILY_XML_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
THOUSAND = Decimal("1000")
_MIN_PRICED_MODELS = {"routerai": 100, "openrouter": 100}


@dataclass(frozen=True)
class ProviderPricingCatalog:
    provider: str
    rows: list[tuple[str, Decimal, Decimal]]
    source: str


def _fetch_json(url: str) -> list[dict]:
    request = Request(url, headers={"User-Agent": "GPTHub-pricing-sync/1.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS catalog URLs
        payload = json.load(response)
    return list(payload.get("data") or [])


def _usd_to_rub() -> Decimal:
    pinned = os.environ.get("OPENROUTER_USD_TO_RUB", "").strip()
    if pinned:
        return Decimal(pinned)
    with urlopen(CBR_DAILY_XML_URL, timeout=30) as response:  # noqa: S310 -- official HTTPS URL
        root = ET.fromstring(response.read())
    for currency in root.findall("Valute"):
        if currency.findtext("CharCode") == "USD":
            nominal = Decimal(currency.findtext("Nominal", "1").replace(",", "."))
            value = Decimal(currency.findtext("Value", "").replace(",", "."))
            return value / nominal
    raise RuntimeError("USD rate was not found in the Bank of Russia daily XML")


def _decimal(pricing: dict, key: str) -> Decimal:
    value = pricing.get(key)
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


def _rates(
    rows: list[dict], *, usd_to_rub: Decimal = Decimal(1)
) -> list[tuple[str, Decimal, Decimal]]:
    out: list[tuple[str, Decimal, Decimal]] = []
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        pricing = row.get("pricing") or {}
        if not model_id or not isinstance(pricing, dict):
            continue
        prompt = _decimal(pricing, "prompt")
        completion = _decimal(pricing, "completion") or _decimal(pricing, "image_output")
        if prompt < 0 and completion < 0:
            continue  # Dynamic router price; runtime uses the conservative fallback.
        if prompt < 0 or completion < 0:
            raise ValueError(f"{model_id}: provider catalog returned a negative price")
        prompt *= THOUSAND * usd_to_rub
        completion *= THOUSAND * usd_to_rub
        if prompt <= 0 and completion <= 0:
            continue
        out.append((model_id, prompt, completion))
    return out


def _validate_catalog(provider: str, rows: list[tuple[str, Decimal, Decimal]]) -> None:
    """Fail closed before a partial catalog can delete the previous price set."""
    minimum = _MIN_PRICED_MODELS[provider]
    if len(rows) < minimum:
        raise RuntimeError(
            f"{provider}: expected at least {minimum} priced models, got {len(rows)}; "
            "refusing import"
        )
    model_ids = [model_id for model_id, _, _ in rows]
    if len(set(model_ids)) != len(model_ids):
        raise RuntimeError(f"{provider}: duplicate model ids in provider catalog; refusing import")


def fetch_provider_pricing_catalogs() -> list[ProviderPricingCatalog]:
    """Fetch both catalogs before any database mutation can begin."""
    routerai_rows = _rates(_fetch_json(ROUTERAI_MODELS_URL))
    _validate_catalog("routerai", routerai_rows)
    usd_to_rub = _usd_to_rub()
    openrouter_rows = _rates(_fetch_json(OPENROUTER_MODELS_URL), usd_to_rub=usd_to_rub)
    _validate_catalog("openrouter", openrouter_rows)
    stamp = datetime.now(UTC).date().isoformat()
    return [
        ProviderPricingCatalog("routerai", routerai_rows, f"sync:routerai:{stamp}"),
        ProviderPricingCatalog(
            "openrouter", openrouter_rows, f"sync:openrouter:{stamp}:cbr-usd-{usd_to_rub:.6f}"
        ),
    ]
