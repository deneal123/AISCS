"""Small read-only projection of existing availability evidence; never probes."""

from __future__ import annotations


async def cached_provider_status() -> dict:
    from service.domain.client import active, circuit_breaker, provider_policy
    from service.domain.client.registry import PROVIDER_MODULES, get_spec

    names = list(PROVIDER_MODULES)
    disabled = provider_policy.disabled_providers()
    blocked = await provider_policy.blocked_providers(names)
    down = await circuit_breaker.down_providers(names)
    primary = active.get_active_provider()
    rows = []
    for name, module in PROVIDER_MODULES.items():
        runtime = getattr(module, "_RUNTIME", None)
        spec = get_spec(name)
        evidence = (
            runtime.models.cached_health(runtime.catalog_configuration_generation())
            if runtime is not None
            else {"state": "unknown", "checked_at": None}
        )
        state = (
            "disabled"
            if name in disabled
            else "unavailable"
            if name in blocked | down
            else evidence["state"]
        )
        rows.append(
            {
                "id": name,
                "label": spec.label if spec is not None else name,
                "primary": name == primary,
                "state": state,
                "checked_at": evidence["checked_at"],
            }
        )
    eligible = [row for row in rows if row["state"] != "disabled"]
    ready = sum(row["state"] == "ready" for row in eligible)
    state = (
        "available"
        if ready and ready == len(eligible)
        else "degraded"
        if ready
        else "unknown"
        if any(row["state"] in {"unknown", "stale"} for row in eligible)
        else "unavailable"
    )
    return {"state": state, "ready": ready, "total": len(eligible), "providers": rows}
