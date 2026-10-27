import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.infrastructure import public_web_fetch as fetch
from service.shared.net_guard import UnsafeUrlError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "blocked", "timeout"])
async def test_direct_failure_retries_once_through_proxy(monkeypatch, failure):
    monkeypatch.setattr(fetch, "public_web_proxy", lambda: "http://proxy.example:8080")
    calls = []

    async def attempt(url, headers, timeout, proxy):
        calls.append(proxy)
        if proxy is None:
            if failure == "transport":
                raise httpx.ConnectError("private marker")
            if failure == "timeout":
                raise TimeoutError
            response = httpx.Response(403, request=httpx.Request("GET", url))
            response.raise_for_status()
        return httpx.Response(200)

    response = await fetch.fetch_with_proxy_fallback("https://example.com", {}, 2, attempt)
    assert response.status_code == 200
    assert calls == [None, "http://proxy.example:8080"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unsafe", "not_found", "success"])
async def test_non_retryable_or_success_does_not_use_proxy(monkeypatch, failure):
    monkeypatch.setattr(fetch, "public_web_proxy", lambda: "http://proxy.example:8080")
    calls = []

    async def attempt(url, headers, timeout, proxy):
        calls.append(proxy)
        if failure == "unsafe":
            raise UnsafeUrlError("blocked")
        response = httpx.Response(
            404 if failure == "not_found" else 200, request=httpx.Request("GET", url)
        )
        response.raise_for_status()
        return response

    if failure == "success":
        await fetch.fetch_with_proxy_fallback("https://example.com", {}, 2, attempt)
    else:
        with pytest.raises((UnsafeUrlError, httpx.HTTPStatusError)):
            await fetch.fetch_with_proxy_fallback("https://example.com", {}, 2, attempt)
    assert calls == [None]


def test_internal_parse_route_returns_flat_string_contract(monkeypatch):
    from service.domain.tools.search import client as web_search
    from service.presentation.routers.capabilities import tools

    async def parsed(url):
        return {"content": "page text", "title": "title", "error": None}

    monkeypatch.setattr(tools, "internal_auth", lambda _key: None)
    monkeypatch.setattr(web_search, "parse_url", parsed)
    app = FastAPI()
    app.include_router(tools.router)
    with TestClient(app) as client:
        response = client.post("/tools/parse-url", json={"url": "https://example.com"})
    assert response.json() == {"content": "page text"}


@pytest.mark.asyncio
async def test_proxy_redirect_to_private_host_is_still_blocked(monkeypatch):
    from service.domain.tools.search import client as web_search

    checked = []

    async def guard(host):
        checked.append(host)
        if host == "127.0.0.1":
            raise UnsafeUrlError("blocked")

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    original = httpx.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        kwargs.pop("proxy")
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(web_search, "_assert_public_host", guard)
    monkeypatch.setattr(web_search.httpx, "AsyncClient", client)
    with pytest.raises(UnsafeUrlError):
        await web_search._fetch_url_attempt("https://example.com", {}, 2, "http://proxy:80")
    assert checked == ["example.com", "127.0.0.1"]
