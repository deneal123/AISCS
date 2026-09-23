"""Контракт `POST /route` — ручки, по ответу которой backend ТАРИФИЦИРУЕТ роутер-ЛЛМ.

Написан после того, как ручка молча умерла: при переезде домена в сабмодуль модуль
`model_routing_service` не поехал, импорт стоял ВНУТРИ обработчика под широким
`except`, и /route отдавал 503 на каждый запрос. Backend это проглатывал (fail-open)
и слал сообщения вообще без роутинга — никаких падений, просто пропавшая функция.

Поэтому тут проверяется не «двести», а три вещи, каждая из которых тогда сломалась:
  * модуль роутинга ЕСТЬ (регрессия «не переехал» ловится на импорте);
  * `routing_usage` доезжает в ответе — потеряется, и вызов достанется бесплатно;
  * авто-инструмент раскладывается во флаги, а явный выбор пользователя не затирается.
"""

import pytest
from fastapi.testclient import TestClient

from service import main as sidecar
from service.presentation import runtime


@pytest.fixture()
def client(monkeypatch):
    """Клиент с внутренним ключом: `/route` закрыт (см. test_internal_auth.py)."""
    from service.settings import config

    key = "test-internal-key"
    monkeypatch.setattr(config.agents, "llm_gateway_api_key", key, raising=False)
    return TestClient(sidecar.app, headers={"Authorization": f"Bearer {key}"})


def _body(**over):
    body = {
        "text": "Сколько будет два плюс два?",
        "selected_model": None,
        "input_type": "text",
        "web_search": False,
        "deep_research": False,
        "route_override": None,
    }
    body.update(over)
    return body


def test_routing_module_is_present():
    """Сам факт «модуль на месте» — та регрессия, что жила незамеченной."""
    assert runtime.ModelRoutingService is not None, runtime.ROUTING_ERROR
    assert runtime.ROUTING_ERROR is None


def test_health_reports_routing(client):
    body = client.get("/health").json()
    assert body["routing"]["available"] is True
    assert body["routing"]["error"] is None


def test_route_returns_usage_and_flags(client, monkeypatch):
    """usage роутер-ЛЛМ обязан доехать до backend — по нему идёт отдельная тарификация."""

    async def fake_route_model(*, text, selected_model, input_type, execution=None, **_):
        execution.usage.record_usage(
            {"prompt": 592, "completion": 30}, model="openai/gpt-4o-mini", kind="route_model"
        )
        return "openai/gpt-4o-mini", {"tool": "web_search"}

    import service.domain.tools.router as router_mod

    monkeypatch.setattr(router_mod, "route_model", fake_route_model)

    data = client.post("/route", json=_body()).json()

    assert data["selected_model"] == "openai/gpt-4o-mini"
    assert data["routing_usage"]["prompt"] == 592
    assert data["routing_usage"]["completion"] == 30
    assert data["routing_usage"]["total"] == 622
    assert len(data["routing_usage"]["calls"]) == 1
    # tool=web_search должен подняться во флаг, а не остаться только в метаданных
    assert data["web_search"] is True
    assert data["routing_metadata"]["tool"] == "web_search"


def test_route_keeps_explicit_user_choice(client, monkeypatch):
    """Авто-инструмент НЕ должен перебивать то, что пользователь потребовал сам."""

    async def fake_route_model(*, text, selected_model, input_type, execution=None, **_):
        return "openai/gpt-4o-mini", {"tool": "web_search"}

    import service.domain.tools.router as router_mod

    monkeypatch.setattr(router_mod, "route_model", fake_route_model)

    data = client.post("/route", json=_body(deep_research=True)).json()

    assert data["deep_research"] is True
    # web_search не поднялся: пользователь уже выбрал deep_research
    assert data["web_search"] is False


def test_route_without_router_llm_reports_empty_usage(client, monkeypatch):
    """Ручной режим: роутер-ЛЛМ не звался → usage пуст, тарифицировать нечего."""

    async def fake_route_model(*, text, selected_model, input_type, execution=None, **_):
        return "openai/gpt-4o-mini", {"tool": "none"}

    import service.domain.tools.router as router_mod

    monkeypatch.setattr(router_mod, "route_model", fake_route_model)

    data = client.post("/route", json=_body(selected_model="openai/gpt-4o-mini")).json()

    assert data["routing_usage"] == {}


def test_route_failure_is_502_not_503(client, monkeypatch):
    """502 «не смог» против 503 «меня нет»: backend не должен путать сбой с недеплоем."""

    async def boom(**_):
        raise RuntimeError("провайдеры молчат")

    import service.domain.tools.router as router_mod

    monkeypatch.setattr(router_mod, "route_model", boom)

    resp = client.post("/route", json=_body())
    assert resp.status_code == 502
    # Машинный КОД, а не фраза: вызывающий различает случаи по нему, а не по тексту.
    assert resp.json()["error"] == "routing_failed"
