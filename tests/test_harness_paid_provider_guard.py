"""Paid acceptance is explicit, GigaChat-only and passes through real transport."""

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from scripts.harness_live.paid_server import PaidGigaGuard


@pytest.mark.parametrize("module", ["paid_server", "server"])
def test_importing_acceptance_server_does_not_disable_product_diagnostics(module):
    before = logging.root.manager.disable
    transport = httpx.AsyncHTTPTransport.handle_async_request
    importlib.reload(importlib.import_module("scripts.harness_live." + module))
    assert logging.root.manager.disable == before
    assert httpx.AsyncHTTPTransport.handle_async_request is transport


def guard():
    return PaidGigaGuard(
        SimpleNamespace(
            gigachat_base_url="https://giga.example.test/api/v1",
            gigachat_oauth_url="https://oauth.example.test:9443/api/v2/oauth",
        )
    )


@pytest.mark.parametrize(
    "url,body,allowed",
    [
        (
            "https://giga.example.test/api/v1/chat/completions",
            {"model": "GigaChat-3-Lightning"},
            True,
        ),
        ("https://giga.example.test/api/v1/chat/completions", {"model": "GigaChat-2-Max"}, False),
        ("https://api.openai.com/v1/chat/completions", {"model": "GigaChat-3-Lightning"}, False),
        ("http://backend:8002/internal/harness/v1/exchange", {}, True),
        ("http://backend:8000/internal/harness/v1/exchange", {}, False),
    ],
)
def test_only_the_selected_paid_model_and_owned_internal_ports_are_allowed(url, body, allowed):
    assert guard().allows(httpx.Request("POST", url, json=body)) is allowed


@pytest.mark.asyncio
async def test_allowed_response_is_never_fabricated_and_denied_network_never_reached(monkeypatch):
    original = AsyncMock(return_value=httpx.Response(200, json={"real": True}))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", original)
    owner = guard()
    owner.install()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://giga.example.test/api/v1/chat/completions",
            json={"model": "GigaChat-3-Lightning"},
        )
        assert response.json() == {"real": True}
        with pytest.raises(httpx.ConnectError, match="paid_acceptance_transport_denied"):
            await client.post("https://api.openai.com/v1/chat/completions", json={"model": "gpt"})
    assert original.await_count == 1 and owner.completions == 1 and owner.blocked == 1
