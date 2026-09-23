"""Роутинг через сайдкар (остаток Фазы 4): кто решает, какой моделью отвечать.

Роутер — ЛЛМ-вызов, и он исторически делался в ВЕБ-процессе backend'а. После выноса
движка это оставляло второе место, где backend звонит провайдерам сам, мимо всего, чем
владеет сайдкар. Теперь решение принимает сайдкар, а backend деградирует к локальному
роутингу, если тот молчит: без роутинга сообщение не уйдёт вовсе.

⚠️ Главное здесь — ДЕНЬГИ: ``routing_usage`` несёт токены роутер-ЛЛМ, по которым воркер
тарифицирует пользователя ОТДЕЛЬНО. Потеряется при сериализации — вызов достанется
бесплатно; исказится — спишем не то.
"""

from types import SimpleNamespace

import pytest

from service.services.chat.application.model_routing_service import ModelRoutingService


def _cfg(http: bool = True):
    return SimpleNamespace(
        agents=SimpleNamespace(
            sidecar_url="http://agents:8090",
            sidecar_timeout_sec=600.0,
            engine_mode="http" if http else "inprocess",
            engine_canary_user_ids="",
        )
    )


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp=None, boom=None, seen=None):
        self._resp, self._boom = resp, boom
        self._seen = seen if seen is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kw):
        self._seen.update(url=url, **kw)
        if self._boom:
            raise self._boom
        return self._resp


def _patch(monkeypatch, *, http=True, **kwargs):
    monkeypatch.setattr("service.settings.config", _cfg(http))
    seen: dict = {}
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: _Client(seen=seen, **kwargs))
    return seen


@pytest.mark.asyncio
async def test_routing_usage_survives_the_round_trip(monkeypatch) -> None:
    """Токены роутера обязаны доехать в точности — по ним списываются деньги."""
    usage = {"prompt": 120, "completion": 8, "total": 128}
    _patch(
        monkeypatch,
        resp=_Resp(
            200,
            {
                "selected_model": "openai:gpt-4o-mini",
                "routing_metadata": {"tool": "web_search"},
                "web_search": True,
                "deep_research": False,
                "route_override": None,
                "routing_usage": usage,
            },
        ),
    )
    decision = await ModelRoutingService()._resolve_via_sidecar(text="привет")

    assert decision is not None
    assert decision.routing_usage == usage
    assert decision.selected_model == "openai:gpt-4o-mini"
    assert decision.web_search is True
    assert decision.routing_metadata == {"tool": "web_search"}


@pytest.mark.asyncio
async def test_request_carries_the_flags(monkeypatch) -> None:
    seen = _patch(monkeypatch, resp=_Resp(200, {"selected_model": "m"}))
    await ModelRoutingService()._resolve_via_sidecar(
        text="q", selected_model=None, input_type="audio", web_search=False
    )
    assert seen["url"] == "http://agents:8090/route"
    assert seen["json"]["input_type"] == "audio"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"boom": RuntimeError("сеть легла")},
        {"resp": _Resp(503)},
        {"resp": _Resp(200, {"нет": "selected_model"})},
        {"resp": _Resp(200, ["не словарь"])},
    ],
)
async def test_failures_degrade_to_local_routing(monkeypatch, kwargs) -> None:
    """None = «решай сам». Иначе сообщение не ушло бы вовсе."""
    _patch(monkeypatch, **kwargs)
    assert await ModelRoutingService()._resolve_via_sidecar(text="q") is None


@pytest.mark.asyncio
async def test_inprocess_mode_does_not_call_the_sidecar(monkeypatch) -> None:
    _patch(monkeypatch, http=False, boom=AssertionError("in-process: по сети не ходим"))
    assert await ModelRoutingService()._resolve_via_sidecar(text="q") is None


@pytest.mark.asyncio
async def test_empty_usage_stays_empty(monkeypatch) -> None:
    """Ручной выбор модели — роутер-ЛЛМ не звался, тарифицировать нечего."""
    _patch(monkeypatch, resp=_Resp(200, {"selected_model": "m", "routing_usage": {}}))
    decision = await ModelRoutingService()._resolve_via_sidecar(text="q")
    assert decision.routing_usage == {}
