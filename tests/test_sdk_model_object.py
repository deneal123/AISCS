"""Модель в `Agent(model=...)` уходит ОБЪЕКТОМ, иначе слеш в имени ломает запрос.

🔴 SDK разбирает строку модели как `провайдер/модель` (конвенция `MultiProvider`), а у
агрегаторов слеш — ЧАСТЬ ИМЕНИ (`openai/gpt-4o-mini` у RouterAI/OpenRouter). Живой прогон:
строкой → `400 Model 'gpt-4o-mini' not found` (префикс съеден), объектом → полноценный
стрим и рабочий вызов инструмента.

Тест держит именно ФОРМУ передачи: строка здесь — молчаливая поломка, которую видно только
по 400 от провайдера.
"""

from __future__ import annotations

import pytest

from service.domain.runners import sdk_run


class _Client:
    """Достаточно любого объекта: важно, что он дошёл до модели, а не был проигнорирован."""


@pytest.fixture
def active_client(monkeypatch):
    from service.domain.client import provider_compat

    client = _Client()
    monkeypatch.setattr(provider_compat, "active_provider_client", lambda: client)
    return client


def test_model_is_wrapped_into_object(active_client):
    """Имя со слешем не должно уехать строкой — SDK съел бы префикс."""
    model = sdk_run._sdk_model("openai/gpt-4o-mini")

    assert not isinstance(model, str), (
        "модель ушла СТРОКОЙ: SDK разберёт 'openai/gpt-4o-mini' как провайдер+модель "
        "и запросит несуществующую 'gpt-4o-mini' (400 у агрегатора)"
    )
    assert getattr(model, "model", None) == "openai/gpt-4o-mini", "имя модели исказилось"


def test_model_object_uses_provider_client(active_client):
    """Объект обязан нести КЛИЕНТА активного провайдера, иначе уедет к чужой базе/ключу."""
    model = sdk_run._sdk_model("openai/gpt-4o-mini")

    carried = getattr(model, "_client", None) or getattr(model, "openai_client", None)
    assert carried is active_client, "модель собрана с чужим клиентом"


@pytest.mark.asyncio
async def test_runner_passes_object_to_agent(active_client, monkeypatch):
    """🔴 Проверяем МЕСТО ВЫЗОВА, а не только функцию.

    Стражи выше держат `_sdk_model`, но её мог бы перестать звать сам прогон — и тесты
    остались бы зелёными, пока провайдер отвечает 400. Этот класс промаха («тест проверял
    функцию, поломка жила в точке вызова») в проекте уже случался, поэтому смотрим на то,
    что реально доехало до `Agent(model=...)`.
    """
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from service.domain.subagents.general import GeneralAgent
    from service.schemas.agents import UserContext

    seen: dict = {}

    class _Model:
        def __init__(self, model=None, openai_client=None):
            self.model = model
            self.openai_client = openai_client

    class _Run:
        raw_responses: list = []

        async def stream_events(self):
            return
            yield  # pragma: no cover — делает метод генератором

    def _agent(**kw):
        seen.update(kw)
        return SimpleNamespace(**kw)

    fake_sdk = SimpleNamespace(
        Agent=_agent,
        Runner=SimpleNamespace(run_streamed=lambda *a, **k: _Run()),
        RunContextWrapper=lambda payload: payload,
        ModelSettings=lambda **kw: SimpleNamespace(**kw),
        OpenAIChatCompletionsModel=_Model,
    )
    monkeypatch.setitem(__import__("sys").modules, "agents", fake_sdk)

    agent = GeneralAgent({"model": "openai/gpt-4o-mini"})
    ctx = UserContext(user_id="", request_time=datetime.now(UTC))
    [e async for e in agent._run_sdk_streamed("вопрос", ctx)]

    assert "model" in seen, "модель не дошла до Agent(...)"
    assert not isinstance(seen["model"], str), (
        "в Agent(model=...) уехала СТРОКА — SDK съест префикс агрегатора и получит 400"
    )
    assert seen["model"].model == "openai/gpt-4o-mini"


def test_falls_back_to_string_without_client(monkeypatch):
    """Fail-open: нет клиента — отдаём строку, поведение как прежде, а не падение."""
    from service.domain.client import provider_compat

    monkeypatch.setattr(provider_compat, "active_provider_client", lambda: None)

    assert sdk_run._sdk_model("acme/chat") == "acme/chat"
