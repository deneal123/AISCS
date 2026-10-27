"""Bounded private HTTP transport; no retries, task decisions or provider calls."""

import httpx

from service.shared.harness_protocol import Exchange, HarnessFailure

_PUBLIC_FAILURES = frozenset(
    {
        "budget_exhausted",
        "cost_unknown",
        "operation_unknown",
        "cancelled",
        "harness_fenced",
        "binding_changed",
        "provider_state_incompatible",
        "user_decision_required",
        "budget_unavailable",
        "dispatch_disabled",
        "checkpoint_conflict",
        "operation_conflict",
        "task_contract_invalid",
        "task_permission_denied",
        "verification_missing",
        "verification_unavailable",
        "usage_limit_exceeded",
    }
)
_ALIASES = {
    "task_contract_missing": "task_contract_invalid",
    "harness_forbidden": "harness_fenced",
    "deadline_exceeded": "usage_limit_exceeded",
}


async def post_exchange(url, capability, payload: Exchange, *, transport=None) -> dict:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=5, trust_env=False) as client:
            response = await client.post(
                url,
                json=payload.model_dump(mode="json", exclude_none=True),
                headers={"Authorization": "Bearer " + capability},
            )
        if len(response.content) > 2 * 1048576:
            raise HarnessFailure()
        result = response.json()
        if type(result) is not dict:
            raise HarnessFailure()
        if response.status_code != 200:
            detail = result.get("detail")
            code = detail.get("code") if isinstance(detail, dict) else None
            code = _ALIASES.get(code, code) if isinstance(code, str) else None
            raise HarnessFailure(code if code in _PUBLIC_FAILURES else "checkpoint_unavailable")
        return result
    except HarnessFailure:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise HarnessFailure() from None
