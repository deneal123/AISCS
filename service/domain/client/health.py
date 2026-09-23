"""Safe provider health aggregation over typed catalog and generation state."""

from __future__ import annotations

import asyncio
from collections.abc import Collection
from typing import Any

PROBE_TIMEOUT_SEC = 5.0


def classify_provider_error(exc: Exception) -> str:
    """Map provider failures to stable operator-facing labels."""

    from service.domain.client.protocol import classify_provider_failure

    labels = {
        "auth": "нет доступа (ключ)",
        "quota": "исчерпана квота",
        "rate_limit": "лимит запросов",
        "timeout": "таймаут",
        "transport": "недоступен (сеть)",
        "tls": "ошибка TLS",
        "tls_config": "ошибка TLS",
    }
    return labels.get(classify_provider_failure(exc).code.value, "ошибка")


def provider_error_detail(exc: Exception) -> str:
    """Return a bounded code without rendering an upstream response or exception."""

    from service.domain.client.protocol import classify_provider_failure

    return classify_provider_failure(exc).code.value


async def _policy_state(names: list[str], force_probe: bool) -> tuple[set[str], set[str], set[str]]:
    from . import provider_policy
    from .resilience.circuit_breaker import down_providers

    try:
        blocked = await provider_policy.blocked_providers(names)
    except Exception:  # noqa: BLE001 - health remains fail-open with bounded output
        blocked = set()
    disabled = provider_policy.disabled_providers()
    try:
        down = set() if force_probe else await down_providers(names)
    except Exception:  # noqa: BLE001 - traffic breaker is an optional health signal
        down = set()
    return set(blocked), set(disabled), set(down)


async def _balance() -> Any | None:
    from .providers import openrouter as openrouter_client

    try:
        return await asyncio.wait_for(openrouter_client.fetch_balance(), timeout=PROBE_TIMEOUT_SEC)
    except Exception:  # noqa: BLE001 - an optional balance must not hide provider health
        return None


async def compute_provider_health(
    *, force_probe: bool = False, only: Collection[str] | None = None
) -> dict[str, Any]:
    """Return independent, bounded health for each selected provider."""

    from . import get_active_provider
    from .health_probe import ProviderProbeContext, probe_provider
    from .registry import PROVIDER_MODULES

    try:
        active = get_active_provider()
    except Exception:  # noqa: BLE001 - active selection is diagnostic, not availability
        active = None
    names = list(PROVIDER_MODULES)
    blocked, disabled, known_down = await _policy_state(names, force_probe)
    targets = [name for name in names if only is None or name in only]
    context = ProviderProbeContext(
        known_down=frozenset(known_down),
        force_probe=force_probe,
        timeout_sec=PROBE_TIMEOUT_SEC,
    )
    probed, balance = await asyncio.gather(
        asyncio.gather(*(probe_provider(name, context) for name in targets)),
        _balance(),
    )
    results = dict(probed)
    if balance is not None and "openrouter" in results:
        results["openrouter"]["balance"] = balance
    for name, info in results.items():
        info["disabled"] = name in disabled
        info.setdefault("blocked", name in blocked)
    return {"active_provider": active, "providers": results}


__all__ = ["classify_provider_error", "compute_provider_health", "provider_error_detail"]
