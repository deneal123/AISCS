"""Подмена модели при фейловере не должна разорять пользователя — счётная половина.

Живой инцидент: человек выбрал claude-haiku (класс `fast`), у OpenRouter кончился лимит
ключа, фейловер ушёл на RouterAI, а там `_pick_chat_capable_model` брал ПЕРВУЮ по алфавиту
модель — `ai21/jamba-large-1.7` (класс `large`, в 15× дороже). Те же 17k токенов стоили
4505 кредитов вместо 396.

Оборона в три линии, по одной на источник ошибки. Здесь — вторая и третья:

1. фейловер не подставляет модель ДОРОЖЕ выбранной — уехало в сайдкар
   (`agents/tests/cross_service/test_model_substitution_billing.py`), это его реестр;
2. если всё же подставил — счёт капается ценой выбранной модели (`_charge_usage`);
3. пользователь ВИДИТ подмену (`_build_public_usage_meta`).

Линия 1 — единственная превентивная; линии 2-3 ловят инцидент, если она не сработала,
и без них тест «фейловер аккуратен» ничего не гарантирует по деньгам.
"""

import pytest

import service.services.billing.application.billing_service as bs_mod
import service.services.billing.application.pricing_service as ps_mod
import service.services.chat.infrastructure.chat_worker.charging as charging

# ⚠️ Из НАСТОЯЩЕГО места: функция проходила через воркер транзитом и ломалась при выносе.
import service.services.chat.infrastructure.chat_worker.message_meta as message_meta
from service.shared.model_class import classify_model
from tests.test_helpers import FakeConnector, FakeDBSession

###############################################################################
# Потолок цены в _charge_usage                                                #
###############################################################################

# Кредиты, которые фейковая тарификация выдаёт по классу модели — грубо повторяет
# реальный разрыв 396 против 4505.
_CLASS_CREDITS = {"fast": 396, "large": 4505, None: 1000}


class _ClassPricing:
    """PricingService, считающий по КЛАССУ модели из per_call_usage."""

    def __init__(self, *a, **k):
        pass

    async def price_request(self, *, per_call_usage, tools, is_complex):
        model = str((per_call_usage or [{}])[0].get("model") or "")

        class _P:
            credits = _CLASS_CREDITS[classify_model(model)]
            raw_cost_rub = 0.0

        return _P()


def _patch(monkeypatch):
    captured: dict = {"charged": None}

    class _FakeBilling:
        def __init__(self, *a, **k):
            pass

        async def charge(self, user_id, **kw):
            captured["charged"] = {"user_id": user_id, **kw}
            return {"from_subscription": kw.get("credits", 0), "from_topup": 0}

        async def release_reservation(self, *a, **k):
            pass

    monkeypatch.setattr(charging, "_overlay_billing", lambda pg, cfg: object())
    monkeypatch.setattr(bs_mod, "BillingService", _FakeBilling)
    monkeypatch.setattr(ps_mod, "PricingService", _ClassPricing)
    return captured


@pytest.mark.asyncio
async def test_substitution_is_capped_to_chosen_model_price(monkeypatch) -> None:
    """Ответила large-модель, а выбрана fast → списываем по fast, не по large."""
    captured = _patch(monkeypatch)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={
            "total_tokens": 17368,
            "reply_chars_count": 5000,
            "prompt_tokens": 14184,
            "completion_tokens": 3184,
            # Пользователь выбрал haiku, но ответила подставленная jamba-large.
            "per_call_usage": [
                {"model": "ai21/jamba-large-1.7", "prompt": 14184, "completion": 3184}
            ],
        },
        thread_id="t",
        job_id="job-sub",
        resolved_model="~anthropic/claude-haiku-latest",
        config=object(),
        reservation_id="r1",
        reserved_estimate=60,
    )
    assert credits == 396, "счёт обязан капнуться ценой ВЫБРАННОЙ модели"
    assert captured["charged"]["credits"] == 396
    assert captured["charged"]["metadata"]["billing_fallback"] == "model_substitution_capped"


@pytest.mark.asyncio
async def test_no_substitution_no_cap(monkeypatch) -> None:
    """Ответила та же модель, что выбрана → потолок не трогает нормальный счёт."""
    captured = _patch(monkeypatch)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={
            "total_tokens": 17368,
            "reply_chars_count": 5000,
            "prompt_tokens": 14184,
            "completion_tokens": 3184,
            "per_call_usage": [
                {"model": "ai21/jamba-large-1.7", "prompt": 14184, "completion": 3184}
            ],
        },
        thread_id="t",
        job_id="job-nosub",
        resolved_model="ai21/jamba-large-1.7",  # выбрали её же
        config=object(),
        reservation_id="r1",
        reserved_estimate=60,
    )
    assert credits == 4505, "без подмены платит как обычно"
    assert captured["charged"]["metadata"].get("billing_fallback") is None


@pytest.mark.asyncio
async def test_cheaper_substitution_is_not_marked_up(monkeypatch) -> None:
    """Подставили ДЕШЕВЛЕ выбранного — счёт по факту, потолок не поднимает цену."""
    captured = _patch(monkeypatch)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={
            "total_tokens": 1000,
            "reply_chars_count": 500,
            "prompt_tokens": 800,
            "completion_tokens": 200,
            "per_call_usage": [{"model": "google/gemma-2-9b", "prompt": 800, "completion": 200}],
        },
        thread_id="t",
        job_id="job-cheap",
        resolved_model="ai21/jamba-large-1.7",  # выбрали дорогую, ответила дешёвая
        config=object(),
        reservation_id="r1",
        reserved_estimate=60,
    )
    assert credits == 396, "фактический (дешёвый) счёт, без наценки до выбранного"
    assert captured["charged"]["metadata"].get("billing_fallback") is None


###############################################################################
# Пользователь видит подмену                                                  #
###############################################################################


def test_public_usage_meta_exposes_substitution() -> None:
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 17368,
            "prompt_tokens": 14184,
            "completion_tokens": 3184,
            "per_call_usage": [
                {"model": "ai21/jamba-large-1.7", "prompt": 14184, "completion": 3184}
            ],
        },
        charged_credits=396,
        model="~anthropic/claude-haiku-latest",
        duration_ms=1000,
    )
    assert meta["model"] == "~anthropic/claude-haiku-latest", "показываем ВЫБОР пользователя"
    assert meta["actual_model"] == "ai21/jamba-large-1.7", "и кто ответил на самом деле"


def test_public_usage_meta_silent_when_no_substitution() -> None:
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 1000,
            "prompt_tokens": 800,
            "completion_tokens": 200,
            "per_call_usage": [{"model": "m", "prompt": 800, "completion": 200}],
        },
        charged_credits=10,
        model="m",
        duration_ms=500,
    )
    assert "actual_model" not in meta, "без подмены лишнего поля нет"


###############################################################################
# Пользователь понимает, из чего сложился счёт                                #
###############################################################################


def _price(*, surcharges, is_complex=False, prompt=2193, completion=739):
    from decimal import Decimal

    from service.services.billing.domain.pricing import ModelPrice, PricingParams, compute_credits

    rub = Decimal("0.3")
    return compute_credits(
        per_call_prices=[(prompt, completion, ModelPrice(rub, rub))],
        tool_surcharges_rub=[Decimal(str(s)) for s in surcharges],
        is_complex=is_complex,
        params=PricingParams(
            credit_unit_rub=Decimal("0.003"),
            margin_multiplier=Decimal("2.5"),
            complexity_factor_complex=Decimal("1.15"),
            min_credits_per_request=1,
        ),
    )


def test_surcharge_share_matches_the_real_charge() -> None:
    """🔴 Доля надбавки — РАЗНИЦА двух прогонов формулы, а не отдельное выражение.

    Числа взяты из живого сообщения: 2193+739 токенов на GigaChat-2-Max дали 733
    кредита, списано 1567 — надбавка за веб-поиск оказалась БОЛЬШЕ ПОЛОВИНЫ счёта, и
    объяснить это по паре «2.9k т. · 1567 кр.» было нечем.
    """
    without = _price(surcharges=[])
    with_search = _price(surcharges=[1.0])

    assert without.credits == 733
    assert with_search.credits == 1567
    assert with_search.surcharge_credits == 1567 - 733, "доля надбавки разошлась со счётом"


def test_surcharge_share_survives_complexity_and_ceiling() -> None:
    """Complexity и округление вверх применяются к СУММЕ — доля обязана это учитывать."""
    without = _price(surcharges=[], is_complex=True)
    with_tools = _price(surcharges=[1.0, 5.0], is_complex=True)

    assert with_tools.surcharge_credits == with_tools.credits - without.credits


def test_no_surcharge_no_share() -> None:
    assert _price(surcharges=[]).surcharge_credits == 0


def test_breakdown_reaches_the_user() -> None:
    """Разбивка обязана доехать до метаданных сообщения — иначе её никто не увидит."""
    meta = message_meta.build_public_usage_meta(
        {"total_tokens": 2932, "prompt_tokens": 2193, "completion_tokens": 739},
        charged_credits=1567,
        model="GigaChat-2-Max",
        duration_ms=14532,
        breakdown={"surcharge_credits": 834, "surcharged_tools": ["web_search"]},
    )
    assert meta["surcharge_credits"] == 834
    assert meta["surcharged_tools"] == ["web_search"]


def test_no_breakdown_no_noise() -> None:
    """Без надбавки лишних полей в метаданных нет."""
    meta = message_meta.build_public_usage_meta(
        {"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20},
        charged_credits=10,
        model="m",
        duration_ms=100,
    )
    assert "surcharge_credits" not in meta
    assert "surcharged_tools" not in meta


def test_service_calls_do_not_count_as_substitution() -> None:
    """🔴 Служебный вызов на мета-модели — НЕ подмена.

    Замерено живьём: на выбранной `GigaChat-2-Max` ответ дал именно GigaChat, а рядом
    отработала декомпозиция на `gpt-4o-mini` — и бейдж «замена модели» загорался. В
    разобранном диалоге он горел на трёх ответах из четырёх, так что отличить настоящий
    фейловер от обычной работы стало нельзя.
    """
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 1500,
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "per_call_usage": [
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 575,
                    "completion": 27,
                    "kind": "meta_usage",
                },
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 300,
                    "completion": 20,
                    "kind": "route_model",
                },
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 120,
                    "completion": 12,
                    "kind": "query_resolution",
                },
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 90,
                    "completion": 10,
                    "kind": "research_plan",
                },
                {"model": "GigaChat-2-Max", "prompt": 917, "completion": 253},
            ],
        },
        charged_credits=318,
        model="GigaChat-2-Max",
        duration_ms=6359,
    )
    assert "actual_model" not in meta, "служебный вызов объявлен подменой — бейдж врёт"


def test_real_failover_is_still_visible_among_service_calls() -> None:
    """🔴 Обратная сторона: настоящую подмену прятать НЕЛЬЗЯ, это денежный признак."""
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 1500,
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "per_call_usage": [
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 575,
                    "completion": 27,
                    "kind": "meta_usage",
                },
                {"model": "routerai/llama", "prompt": 917, "completion": 253},
            ],
        },
        charged_credits=318,
        model="GigaChat-2-Max",
        duration_ms=6359,
    )
    assert meta["actual_model"] == "routerai/llama", "настоящий фейловер спрятан"


def test_document_visual_audit_is_not_reported_as_answer_model_substitution() -> None:
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 420,
            "prompt_tokens": 400,
            "completion_tokens": 20,
            "per_call_usage": [
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt": 400,
                    "completion": 20,
                    "kind": "document_visual_audit",
                }
            ],
        },
        charged_credits=12,
        model="GigaChat-3-Lightning",
        duration_ms=500,
    )

    assert "actual_model" not in meta


def test_multi_intent_step_counts_as_an_answer() -> None:
    """Шаг мульти-интента порождает текст ответа — его модель это «кто ответил»."""
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 900,
            "prompt_tokens": 700,
            "completion_tokens": 200,
            "per_call_usage": [
                {
                    "model": "routerai/llama",
                    "prompt": 700,
                    "completion": 200,
                    "kind": "multi_intent_usage",
                },
            ],
        },
        charged_credits=100,
        model="GigaChat-2-Max",
        duration_ms=1000,
    )
    assert meta["actual_model"] == "routerai/llama"


def test_old_sidecar_without_kind_behaves_as_before() -> None:
    """⚠️ Нет `kind` → считаем ОТВЕТОМ. Старый сайдкар шумит, но ничего не скрывает.

    Обратное умолчание («нет метки — значит служебный») прятало бы настоящую подмену на
    всём окне рассинхрона версий, а это денежный признак.
    """
    meta = message_meta.build_public_usage_meta(
        {
            "total_tokens": 900,
            "prompt_tokens": 700,
            "completion_tokens": 200,
            "per_call_usage": [{"model": "routerai/llama", "prompt": 700, "completion": 200}],
        },
        charged_credits=100,
        model="GigaChat-2-Max",
        duration_ms=1000,
    )
    assert meta["actual_model"] == "routerai/llama"


@pytest.mark.asyncio
async def test_ceiling_falls_back_to_selected_model_when_resolved_none(monkeypatch) -> None:
    """T3.6: resolved_model=None → потолок по ИСХОДНОМУ selected_model, а не «без потолка».

    Иначе при упавшем роутинге (resolved_model=None) подставленная фейловером large-модель
    списывалась бы БЕЗ потолка — юзер платит неограниченную цену чужой модели.
    """
    captured = _patch(monkeypatch)
    credits = await charging._charge_usage(
        pg_connector=FakeConnector(FakeDBSession()),
        redis_client=None,
        user_id="u1",
        execution_result={
            "total_tokens": 17368,
            "reply_chars_count": 5000,
            "prompt_tokens": 14184,
            "completion_tokens": 3184,
            "per_call_usage": [
                {"model": "ai21/jamba-large-1.7", "prompt": 14184, "completion": 3184}
            ],
        },
        thread_id="t",
        job_id="job-none",
        resolved_model=None,  # роутинг не резолвил модель
        selected_model="~anthropic/claude-haiku-latest",  # но юзер выбирал fast
        config=object(),
        reservation_id="r1",
        reserved_estimate=60,
    )
    assert credits == 396, "потолок обязан применяться по selected_model, а не отсутствовать"
    assert captured["charged"]["metadata"]["billing_fallback"] == "model_substitution_capped"
