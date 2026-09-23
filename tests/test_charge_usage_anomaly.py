"""Потеря `per_call_usage` обязана быть ВИДНА в логах.

⚠️ Почему это отдельный тест, а не «и так заметим». `per_call_usage` — единственный
источник цены. Потеряй его сайдкар (переименование поля, сбой сборки result-dict),
и `price_request` получит пустой список → вернёт `min_credits_per_request`, то есть
ОДИН кредит вместо тысяч.

Ни одна существующая проверка при этом не срабатывает:
  * флор по `total_tokens <= 0` не включится — токены-то пришли;
  * warning про нулевое списание не сработает — кредит-то один, а не ноль.

То есть недобилл проходит совершенно молча. Единственное, что от него защищает, —
явная запись в лог, и её здесь и закрепляем.
"""

import logging

import pytest

import service.services.billing.application.billing_service as bs_mod
import service.services.billing.application.pricing_service as ps_mod
import service.services.chat.infrastructure.chat_worker.charging as charging
from tests.test_helpers import FakeConnector, FakeDBSession


def _patch_billing(monkeypatch, *, credits: int):
    captured: dict = {"charged": None}

    class _FakeBilling:
        def __init__(self, *a, **k):
            pass

        async def charge(self, user_id, **kw):
            captured["charged"] = {"user_id": user_id, **kw}
            return {"from_subscription": kw.get("credits", 0), "from_topup": 0}

        async def release_reservation(self, *a, **k):
            pass

    class _FakePrice:
        def __init__(self, credits_: int) -> None:
            self.credits = credits_
            self.raw_cost_rub = 0.0
            self.model_breakdown = []

    class _FakePricing:
        def __init__(self, *a, **k):
            pass

        async def price_request(self, **kw):
            return _FakePrice(credits)

    monkeypatch.setattr(charging, "_overlay_billing", lambda pg, cfg: object())
    monkeypatch.setattr(bs_mod, "BillingService", _FakeBilling)
    monkeypatch.setattr(ps_mod, "PricingService", _FakePricing)
    return captured


@pytest.fixture()
def capture_worker_logs(caplog):
    """Перехват записей воркера НЕЗАВИСИМО от порядка тестов.

    ⚠️ Без этого тест зелёный в одиночку и красный в наборе. Причина: `LOGGING` в
    `service/settings.py` объявляет логгер `service` с `propagate: False`, а
    `service/main.py` применяет этот dictConfig на импорте. Стоит любому соседнему тесту
    импортировать `main` раньше — и записи перестают доходить до корневого
    перехватчика pytest. То есть результат зависел бы от ПОРЯДКА сборки тестов, а такой
    тест не страж, а лотерея.
    """
    # ⚠️ Логгер ТОГО модуля, где живёт списание: биллинг хода вынесен в
    # `chat_worker/charging.py`, и запись идёт от его имени. Прежнее имя дало бы пустой
    # caplog — страж «аномалия не молчит» превратился бы в «лога нет».
    worker_logger = logging.getLogger(charging.__name__)
    worker_logger.addHandler(caplog.handler)
    previous = worker_logger.level
    worker_logger.setLevel(logging.ERROR)
    try:
        yield caplog
    finally:
        worker_logger.removeHandler(caplog.handler)
        worker_logger.setLevel(previous)


async def _charge(execution_result: dict):
    return await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result=execution_result,
        thread_id="t",
        job_id="job-anomaly",
        resolved_model="m",
        config=object(),
        reservation_id=None,
        reserved_estimate=0,
    )


@pytest.mark.asyncio
async def test_missing_per_call_usage_is_logged_as_anomaly(
    monkeypatch, capture_worker_logs
) -> None:
    """Токены есть, разбивки нет → в логах bounded ERROR без номера задачи.

    Без этой записи расхождение контракта сайдкара обнаруживалось бы только по счёту
    от провайдера в конце месяца.
    """
    _patch_billing(monkeypatch, credits=1)

    with capture_worker_logs.at_level(logging.ERROR):
        await _charge({"total_tokens": 5000, "reply_chars_count": 100, "per_call_usage": []})

    anomalies = [
        record
        for record in capture_worker_logs.records
        if getattr(record, "failure_code", None) == "usage_breakdown_missing"
    ]
    assert anomalies, "потеря per_call_usage прошла молча — это недобилл без следов"
    assert "job-anomaly" not in anomalies[0].getMessage()
    assert getattr(anomalies[0], "component", None) == "billing"


def _capture_pricing(monkeypatch):
    """Подменяет PricingService так, чтобы видеть, КАКОЙ per_call_usage дошёл до цены."""
    seen: dict = {"per_call_usage": None}

    class _FakePrice:
        credits = 777
        raw_cost_rub = 0.0
        model_breakdown: list = []

    class _FakePricing:
        def __init__(self, *a, **k):
            pass

        async def price_request(self, *, per_call_usage, tools, is_complex):
            seen["per_call_usage"] = per_call_usage
            return _FakePrice()

    monkeypatch.setattr(ps_mod, "PricingService", _FakePricing)
    return seen


@pytest.mark.asyncio
async def test_missing_per_call_usage_is_reconstructed_from_totals(monkeypatch) -> None:
    """Разбивки нет → цена ВОССТАНАВЛИВАЕТСЯ из агрегатов, а не платится по флору.

    🔴 Лог не возвращает денег. Раньше аномалия только писалась в лог, а `price_request`
    получал пустой список и возвращал `min_credits_per_request` — один кредит вместо тысяч.
    Агрегаты (`prompt_tokens`/`completion_tokens`) лежат в result-dict ОТДЕЛЬНО и переживают
    потерю разбивки, поэтому из них восстанавливается ровно та же цена.
    """
    _patch_billing(monkeypatch, credits=1)
    seen = _capture_pricing(monkeypatch)

    await _charge(
        {
            "total_tokens": 5000,
            "prompt_tokens": 4000,
            "completion_tokens": 1000,
            "reply_chars_count": 100,
            "per_call_usage": [],
        }
    )

    assert seen["per_call_usage"] == [{"model": "m", "prompt": 4000, "completion": 1000}], (
        "цена посчитана по ПУСТОМУ per_call_usage → min-флор вместо реальной суммы (недобилл)"
    )


@pytest.mark.asyncio
async def test_reconstruction_without_breakdown_puts_all_in_prompt(monkeypatch) -> None:
    """Совсем нет разбивки (только total) → всё в prompt: дешёвая половина тарифа.

    При неизвестном составе счёт не задирается сверх фактически известного — но и не
    падает до одного кредита.
    """
    _patch_billing(monkeypatch, credits=1)
    seen = _capture_pricing(monkeypatch)

    await _charge({"total_tokens": 5000, "reply_chars_count": 100, "per_call_usage": []})

    assert seen["per_call_usage"] == [{"model": "m", "prompt": 5000, "completion": 0}]


@pytest.mark.asyncio
async def test_normal_usage_is_not_reconstructed(monkeypatch) -> None:
    """Обратная сторона: при живой разбивке её НЕ подменяем восстановленной."""
    _patch_billing(monkeypatch, credits=120)
    seen = _capture_pricing(monkeypatch)

    real = [{"model": "m", "prompt": 4000, "completion": 1000}]
    await _charge(
        {
            "total_tokens": 5000,
            "prompt_tokens": 1,  # агрегаты расходятся с разбивкой — верить надо РАЗБИВКЕ
            "completion_tokens": 1,
            "reply_chars_count": 100,
            "per_call_usage": real,
        }
    )

    assert seen["per_call_usage"] == real


@pytest.mark.asyncio
async def test_normal_usage_is_not_flagged(monkeypatch, capture_worker_logs) -> None:
    """Обратная сторона: нормальный прогон не должен шуметь.

    Страж, кричащий на штатной работе, перестают читать — и он перестаёт защищать.
    """
    _patch_billing(monkeypatch, credits=120)

    with capture_worker_logs.at_level(logging.ERROR):
        await _charge(
            {
                "total_tokens": 5000,
                "reply_chars_count": 100,
                "per_call_usage": [{"model": "m", "prompt": 4000, "completion": 1000}],
            }
        )

    assert not [r for r in capture_worker_logs.records if "БИЛЛИНГ-АНОМАЛИЯ" in r.getMessage()]


@pytest.mark.asyncio
async def test_no_tokens_at_all_is_not_flagged_here(monkeypatch, capture_worker_logs) -> None:
    """`total_tokens == 0` — это ДРУГОЙ случай, у него свой обработчик (флор).

    Смешивать их нельзя: «провайдер не вернул usage» и «сайдкар потерял разбивку» имеют
    разные причины и разные починки.
    """
    _patch_billing(monkeypatch, credits=1)

    with capture_worker_logs.at_level(logging.ERROR):
        await _charge({"total_tokens": 0, "reply_chars_count": 100, "per_call_usage": []})

    assert not [r for r in capture_worker_logs.records if "БИЛЛИНГ-АНОМАЛИЯ" in r.getMessage()]
