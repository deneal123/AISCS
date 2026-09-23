"""Каталог личностей доезжает до интерфейса ЦЕЛИКОМ, а не только id и label.

🔴 Живая поломка: `hint` (пояснение личности для человека) заводился в реестре сайдкара
ровно затем, чтобы новая личность из админского JSON объясняла себя БЕЗ выката фронта.
Ре-проекция здесь оставляла только `id` и `label`, и все шесть карточек показывали
фолбэк «Специализация из реестра админки». Ошибок при этом не было ни на одной стороне.

Тот же класс потери, что был у `kind` в `per_call_usage`: поле есть у источника и молча
исчезает на нормализации у потребителя. Поэтому страж — на ПЕРЕНОС, а не на форму.
"""

from __future__ import annotations

import pytest

from service.infrastructure.agents_client import sidecar_providers as sp


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    async def request_json(self, _method, _path):
        return self._payload


@pytest.fixture()
def sidecar_returns(monkeypatch):
    def _install(payload):
        monkeypatch.setattr(sp, "_client", lambda *_a, **_kw: _FakeClient(payload))

    return _install


@pytest.mark.asyncio
async def test_hint_survives_normalization(sidecar_returns):
    sidecar_returns(
        {"personas": [{"id": "engineer", "label": "Инженер", "hint": "Ищет, где сломается."}]}
    )

    assert await sp.fetch_persona_catalog(object()) == [
        {"id": "engineer", "label": "Инженер", "hint": "Ищет, где сломается."}
    ]


@pytest.mark.asyncio
async def test_missing_hint_becomes_empty_not_absent(sidecar_returns):
    """Старый сайдкар без `hint` не должен ронять форму: ключ есть, значение пустое."""
    sidecar_returns({"personas": [{"id": "analyst", "label": "Аналитик"}]})

    assert await sp.fetch_persona_catalog(object()) == [
        {"id": "analyst", "label": "Аналитик", "hint": ""}
    ]


@pytest.mark.asyncio
async def test_broken_entries_are_dropped_without_failing(sidecar_returns):
    """Реестр правится руками — мусор отбрасываем, остальные личности работают."""
    sidecar_returns({"personas": ["строка", {"label": "без id"}, {"id": "ok"}]})

    assert await sp.fetch_persona_catalog(object()) == [{"id": "ok", "label": "ok", "hint": ""}]
