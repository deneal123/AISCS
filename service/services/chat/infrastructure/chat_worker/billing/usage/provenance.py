"""Project aggregate provider only when every receipt proves the same transport."""

import logging
from typing import Any

from service.infrastructure.provider_policy_store import PROVIDER_NAMES

logger = logging.getLogger(__name__)


def aggregate_provider(receipts: list[dict[str, Any]]) -> str | None:
    """Mixed/legacy provenance stays per-call; a model prefix cannot prove provider."""
    providers = set()
    for receipt in receipts:
        provider = receipt.get("provider")
        if not isinstance(provider, str) or provider not in PROVIDER_NAMES:
            logger.warning(
                "billing provider provenance unavailable",
                extra={"component": "billing", "failure_code": "usage_provenance"},
            )
            return None
        providers.add(provider)
    return next(iter(providers)) if len(providers) == 1 else None
