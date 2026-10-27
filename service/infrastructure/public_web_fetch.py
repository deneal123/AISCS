"""Bounded direct/proxy fallback for public pages, not internal service traffic."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import quote

import httpx

FetchAttempt = Callable[[str, dict, float, str | None], Awaitable[httpx.Response]]
_RETRY_HTTP = frozenset({403, 408, 429, 451, 502, 503, 504})


def public_web_proxy() -> str | None:
    """Reuse deployment proxy credentials without the LLM-provider allowlist.

    This is exclusively a fallback for public HTTP reads. Internal traffic and
    SSRF validation must never be routed through this proxy.
    """
    from service.settings import config

    settings = config.agents
    host = str(settings.proxy_host or "").strip()
    port = settings.proxy_port
    if not host or not port:
        return None
    if any(char in host for char in "/@?#") or "://" in host:
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    user = quote(str(settings.proxy_user or ""), safe="")
    password = quote(str(settings.proxy_pass or ""), safe="")
    auth = f"{user}:{password}@" if user or password else ""
    return f"http://{auth}{host}:{int(port)}"


async def fetch_with_proxy_fallback(
    url: str, headers: dict, timeout: float, attempt: FetchAttempt
) -> httpx.Response:
    """At most two reads under one wall-clock budget; unsafe URLs never retry.

    Each attempt retains the caller's validation of every redirect. Cancellation
    propagates. TLS verification stays enabled on both paths; no raw failure or
    proxy material is logged here.
    """
    proxy = public_web_proxy()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    direct_budget = timeout / 2 if proxy else timeout
    try:
        return await asyncio.wait_for(attempt(url, headers, direct_budget, None), direct_budget)
    except httpx.HTTPStatusError as exc:
        if not proxy or exc.response.status_code not in _RETRY_HTTP:
            raise
    except (httpx.TransportError, TimeoutError):
        if not proxy:
            raise
    remaining = deadline - loop.time()
    if remaining <= 0:
        raise TimeoutError
    return await asyncio.wait_for(attempt(url, headers, remaining, proxy), remaining)
