"""Private console transport. Lost POST ACK is reconciled, never retried as a run."""

import httpx

from service.shared.harness_protocol import HarnessFailure


async def post_command(url, capability, payload, *, transport=None):
    try:
        async with httpx.AsyncClient(transport=transport, timeout=150, trust_env=False) as client:
            response = await client.post(
                url, json=payload, headers={"Authorization": "Bearer " + capability}
            )
        if len(response.content) > 2 * 1048576:
            raise HarnessFailure()
        value = response.json()
        if response.status_code != 200 or not isinstance(value, dict):
            from service.infrastructure.harness.exchange import _ALIASES, _PUBLIC_FAILURES

            detail = value.get("detail") if isinstance(value, dict) else None
            code = detail.get("code") if isinstance(detail, dict) else None
            if code == "harness_request_invalid":
                raise HarnessFailure(code)
            code = _ALIASES.get(code, code) if isinstance(code, str) else None
            raise HarnessFailure(code if code in _PUBLIC_FAILURES else "checkpoint_unavailable")
        return value
    except (httpx.HTTPError, ValueError, TypeError):
        raise HarnessFailure() from None
