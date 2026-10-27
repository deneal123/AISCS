"""Тесты маршрутизации OpenAI-совместимого шлюза (provider-префикс модели)."""

from unittest.mock import AsyncMock

import pytest

from service.presentation.routers.gateway.openai_v1 import _split_model


def test_split_model_known_prefix():
    assert _split_model("openrouter:openai/gpt-4o-mini") == ("openrouter", "openai/gpt-4o-mini")
    assert _split_model("gigachat:GigaChat") == ("gigachat", "GigaChat")
    assert _split_model("mws:mws-gpt-alpha") == ("mws", "mws-gpt-alpha")


def test_split_model_no_prefix():
    assert _split_model("openai/gpt-4o-mini") == (None, "openai/gpt-4o-mini")
    assert _split_model("gpt-4o-mini") == (None, "gpt-4o-mini")
    assert _split_model("") == (None, "")


def test_split_model_unknown_prefix_is_not_a_provider():
    # неизвестный префикс — не провайдер, модель отдаётся как есть
    assert _split_model("foo:bar") == (None, "foo:bar")


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gigachat:GigaChat-2-Max", "routerai:fixture-model"])
async def test_explicit_prefix_forbids_cross_provider_fallback(monkeypatch, model):
    from service.presentation.routers.gateway import openai_v1 as gateway

    invoke = AsyncMock()
    monkeypatch.setattr(gateway, "invoke_model_call", invoke)
    execution = object()
    await gateway._complete({"model": model, "messages": [], "pin_provider": "openai"}, execution)
    values = invoke.await_args.kwargs
    assert values["provider"] == values["pin_provider"] == model.partition(":")[0]
    assert values["execution"] is execution


@pytest.mark.asyncio
async def test_unprefixed_model_keeps_existing_auto_routing(monkeypatch):
    from service.presentation.routers.gateway import openai_v1 as gateway

    invoke = AsyncMock()
    monkeypatch.setattr(gateway, "invoke_model_call", invoke)
    await gateway._complete({"model": "fixture-model", "messages": []}, object())
    assert invoke.await_args.kwargs["provider"] is None
    assert "pin_provider" not in invoke.await_args.kwargs
