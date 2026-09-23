"""Circuit breaker провайдеров + фильтр каталога + баланс OpenRouter.

Живой инцидент, из-за которого всё это появилось: OpenRouter отдавал 403 «Key limit
exceeded», OpenAI — 429 «insufficient_quota». Раньше breaker гасил только транспорт, а
health-панель проверяла `/models` (бесплатный, отвечает и с нулевой квотой) — поэтому
панель показывала «работает», а пользователи выбирали модели, которые некому обслужить.
"""

import asyncio

import pytest

from service.domain.client.resilience import circuit_breaker as cb


class _HttpErr(Exception):
    """Имитация openai.APIStatusError: несёт status_code."""

    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class _TypedErr(Exception):
    def __init__(self, reason_code: str):
        super().__init__("S24_PRIVATE_PROVIDER_BODY")
        self.reason_code = reason_code


###############################################################################
# should_trip: что считаем падением ПРОВАЙДЕРА, а что — плохим запросом        #
###############################################################################


@pytest.mark.parametrize("code", [401, 403, 429])
def test_trips_on_auth_and_quota_codes(code) -> None:
    """Ровно те коды из инцидента: лимит/квота/доступ — провайдер бесполезен."""
    assert cb.should_trip(_HttpErr(code)) is True


@pytest.mark.parametrize("code", [400, 404, 422])
def test_does_not_trip_on_bad_request_codes(code) -> None:
    """400/404/422 = кривой ОДИН запрос. Погасив, выкинули бы рабочего провайдера."""
    assert cb.should_trip(_HttpErr(code)) is False


def test_trips_on_transport_errors() -> None:
    assert cb.should_trip(TimeoutError("timed out")) is True
    assert cb.should_trip(ConnectionError("connection refused")) is True
    assert cb.should_trip(_TypedErr("transport")) is True


def test_trips_on_typed_money_failures_without_http_status() -> None:
    assert cb.should_trip(_TypedErr("quota")) is True
    assert cb.should_trip(_TypedErr("rate_limit")) is True


def test_ignores_ordinary_errors() -> None:
    assert cb.should_trip(ValueError("unexpected model format")) is False


###############################################################################
# in-memory down-state (быстрый путь фейловера)                               #
###############################################################################


def test_drop_cooled_down_local_removes_marked() -> None:
    asyncio.run(cb.mark_down("openrouter", reason="test"))
    order = ["openrouter", "gigachat", "openai"]
    live = cb.drop_cooled_down_local(order)
    assert "openrouter" not in live
    assert "gigachat" in live and "openai" in live
    asyncio.run(cb.clear_down("openrouter"))
    assert "openrouter" in cb.drop_cooled_down_local(order)


def test_drop_cooled_down_returns_all_when_everyone_down() -> None:
    """Все мертвы → лучше попробовать хоть что-то, чем показать пустоту."""
    order = ["a", "b"]
    asyncio.run(cb.mark_down("a"))
    asyncio.run(cb.mark_down("b"))
    assert set(cb.drop_cooled_down_local(order)) == {"a", "b"}
    asyncio.run(cb.clear_down("a"))
    asyncio.run(cb.clear_down("b"))


@pytest.mark.asyncio
async def test_down_providers_reads_memory() -> None:
    await cb.mark_down("routerai", reason="429")
    down = await cb.down_providers(["routerai", "gigachat"])
    assert "routerai" in down
    assert "gigachat" not in down
    await cb.clear_down("routerai")


###############################################################################
# Каталог прячет модели упавших провайдеров                                   #
###############################################################################


class _FakeProviderModule:
    def __init__(self, name: str) -> None:
        self._models = [f"{name}/model"]
        self.OPENAI_CLIENT = object()

    async def list_available_models(self):
        return self._models


@pytest.mark.asyncio
async def test_catalog_hides_down_provider_models(monkeypatch) -> None:
    from service.domain.client import registry

    fake_modules = {n: _FakeProviderModule(n) for n in ("openrouter", "gigachat")}
    monkeypatch.setattr(registry, "PROVIDER_MODULES", fake_modules)

    # openrouter «мёртв» → его модели в каталог попасть не должны.
    await cb.mark_down("openrouter", reason="test")
    try:
        grouped = await registry._fetch_grouped_models()
        assert "gigachat" in grouped, "живой провайдер остался"
        assert "openrouter" not in grouped, "модели упавшего провайдера не спрятаны"
    finally:
        await cb.clear_down("openrouter")


@pytest.mark.asyncio
async def test_catalog_keeps_all_when_every_provider_down(monkeypatch) -> None:
    """Все мертвы → пустой пикер хуже, чем пикер под страховкой фейловера."""
    from service.domain.client import registry

    fake_modules = {n: _FakeProviderModule(n) for n in ("openrouter", "gigachat")}
    monkeypatch.setattr(registry, "PROVIDER_MODULES", fake_modules)
    await cb.mark_down("openrouter")
    await cb.mark_down("gigachat")
    try:
        grouped = await registry._fetch_grouped_models()
        assert set(grouped) == {"openrouter", "gigachat"}, "не прячем всё до пустоты"
    finally:
        await cb.clear_down("openrouter")
        await cb.clear_down("gigachat")


###############################################################################
# Баланс OpenRouter                                                            #
###############################################################################


@pytest.mark.asyncio
async def test_openrouter_balance_parses(monkeypatch) -> None:
    from service.domain.client.providers import openrouter as orc

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": {"limit": 1, "usage": 1.03, "limit_remaining": 0, "is_free_tier": False}
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(orc, "_resolve_api_key", lambda: "sk-test")
    monkeypatch.setattr(orc, "_make_http_client", lambda: _Client())

    bal = await orc.fetch_balance()
    assert bal["remaining"] == 0, "именно remaining=0 предсказал бы аварию"
    assert bal["limit"] == 1
    assert bal["currency"] == "USD"


@pytest.mark.asyncio
async def test_openrouter_balance_none_without_key(monkeypatch) -> None:
    from service.domain.client.providers import openrouter as orc

    monkeypatch.setattr(orc, "_resolve_api_key", lambda: "")
    assert await orc.fetch_balance() is None


###############################################################################
# Классификатор ошибки для панели                                             #
###############################################################################


def test_error_classifier_reasons() -> None:
    """Классификатор переехал в домен вместе с пробой провайдеров: панель получает
    причину от того, кто реально звонил провайдеру."""
    from service.domain.client.health import classify_provider_error

    assert classify_provider_error(_HttpErr(429)) == "лимит запросов"
    assert classify_provider_error(_HttpErr(403)) == "нет доступа (ключ)"
    assert classify_provider_error(_HttpErr(401)) == "нет доступа (ключ)"
    assert classify_provider_error(TimeoutError("timed out")) == "таймаут"
    assert classify_provider_error(Exception("proxy unreachable")) == "ошибка"


###############################################################################
# T2.1 (аудит): breaker Redis-клиент не должен быть привязан к event loop     #
###############################################################################


def test_breaker_uses_sync_redis_not_loop_bound():
    """Регрессия T2.1: async-Redis привязывается к loop, а воркер celery создаёт новый
    loop на задачу — запись mark_down молча терялась на другом loop, и кросс-процессный
    сигнал не долетал до API-пикера. Клиент обязан быть СИНХРОННЫМ + вызовы через to_thread.
    """
    import inspect

    from service.domain.client.resilience import circuit_breaker as cb

    getter = inspect.getsource(cb._get_redis)
    assert "import redis" in getter and "redis.asyncio" not in getter, (
        "breaker снова на async-Redis — вернётся loop-affinity"
    )
    for fn in (cb.mark_down, cb.clear_down, cb.down_providers):
        assert "to_thread" in inspect.getsource(fn), (
            f"{fn.__name__}: sync-Redis обязан вызываться через asyncio.to_thread"
        )


###############################################################################
# T3.2 (аудит): ошибка длины контекста НЕ должна гасить провайдер             #
###############################################################################


def test_context_length_error_does_not_trip():
    """«maximum context length exceeded» без кода — ошибка запроса, не провайдера."""
    assert cb.should_trip(Exception("This model's maximum context length is 8192 tokens")) is False
    assert cb.should_trip(Exception("maximum context length exceeded")) is False
    assert cb.should_trip(Exception("context window exceeded for this request")) is False


def test_typed_money_failures_trip_without_parsing_exception_text():
    assert cb.should_trip(_TypedErr("quota")) is True
    assert cb.should_trip(_TypedErr("rate_limit")) is True
    assert cb.should_trip(_TypedErr("auth")) is True
    assert cb.should_trip(Exception("iteration limit exceeded")) is False
