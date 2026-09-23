"""Резерв кредитов не даёт получить дорогой ответ при нехватке баланса.

⚠️ РЕАЛЬНАЯ ДЫРА В ДЕНЬГАХ. У пользователя баланс был ~1000, потом ~10000 (пополнял
админ), один запрос списал 22751 кредитов. Баланс не ушёл в минус — обрезался до 0
(`GREATEST(0,…)`), но ответ БЫЛ ВЫДАН. Платформа заплатила провайдеру, разницу
(~13000 кредитов) не покрыл никто. Механизм — двойной:

1. **Резерв недооценивал.** `_estimate_reservation_credits` брал только текст сообщения
   (сотни токенов), не видя file_context/историю/вложения. Реальный prompt раздулся до
   89 537 — а гейт «хватает ли баланса» пропустил запрос, потому что оценка была мала.
2. **Нулевой баланс не блокировал.** `has_sufficient_credits` существовала, но в
   чат-пути не вызывалась. Юзер уходил в 0, а запросы продолжали выполняться.

Оба закрыты: оценка учитывает размер входного контекста; нулевой баланс — жёсткий стоп
ДО прогона.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import chat_worker_tasks as cwt


# --------------------------------------------------------------------------- #
# B1: оценка резерва учитывает входной контекст                                #
# --------------------------------------------------------------------------- #
class _FakePricing:
    """Тариф: кредиты пропорциональны сумме prompt+completion — масштаб важен, не точность."""

    def __init__(self, *a, **k):
        pass

    async def price_request(self, *, per_call_usage, tools, is_complex):
        call = per_call_usage[0]
        credits = int(call["prompt"]) + int(call["completion"])

        class _P:
            pass

        p = _P()
        p.credits = credits
        return p


@pytest.fixture
def fake_pricing(monkeypatch):
    import service.services.billing.application.pricing_service as ps
    import service.services.billing.persistence.pricing_repository as pr

    monkeypatch.setattr(ps, "PricingService", _FakePricing)
    monkeypatch.setattr(pr, "PricingRepository", lambda *a, **k: None)


class _Cfg:
    reserve_safety = 1.2


@pytest.mark.asyncio
async def test_estimate_grows_with_context_size(fake_pricing):
    """⚠️ ГЛАВНОЕ: большой входной контекст → большая оценка резерва.

    Раньше оценка не зависела от контекста вовсе — отсюда и дыра.
    """
    small = await cwt._estimate_reservation_credits(
        pg_connector=None, billing_cfg=_Cfg(), text="привет", selected_model="m", context_chars=0
    )
    big = await cwt._estimate_reservation_credits(
        pg_connector=None,
        billing_cfg=_Cfg(),
        text="привет",
        selected_model="m",
        context_chars=42000,  # ~14k токенов файла
    )

    assert big > small * 5, (
        f"оценка с файлом на 42k символов ({big}) почти не отличается от пустой ({small}) "
        "— резерв снова не увидит раздутый контекст"
    )


@pytest.mark.asyncio
async def test_estimate_applies_tool_loop_factor(fake_pricing):
    """Множитель tool-loop заложен: реальный prompt переотправляется каждый раунд."""
    est = await cwt._estimate_reservation_credits(
        pg_connector=None,
        billing_cfg=_Cfg(),
        text="",
        selected_model="m",
        context_chars=30_000,  # 10k токенов
    )
    # 10k контекста × factor 3 должно дать оценку заметно больше 10k.
    assert est > 10_000, f"оценка {est} не учла переотправку контекста в tool-loop"


@pytest.mark.asyncio
async def test_pdf_estimate_uses_bounded_outline_section_and_one_repair_plan(fake_pricing):
    generic = await cwt._estimate_reservation_credits(
        pg_connector=None,
        billing_cfg=_Cfg(),
        text="Подготовь документ",
        selected_model="m",
        context_chars=30_000,
    )
    document = await cwt._estimate_reservation_credits(
        pg_connector=None,
        billing_cfg=_Cfg(),
        text="Подготовь статью",
        selected_model="m",
        context_chars=30_000,
        route="pdf_gen",
    )

    assert document > generic


@pytest.mark.asyncio
async def test_backward_compatible_default(fake_pricing):
    """context_chars по умолчанию 0 — прямые вызовы/тесты не ломаются."""
    est = await cwt._estimate_reservation_credits(
        pg_connector=None, billing_cfg=_Cfg(), text="вопрос", selected_model="m"
    )
    assert est >= 1


# --------------------------------------------------------------------------- #
# B2: нулевой баланс блокирует ДО прогона                                       #
# --------------------------------------------------------------------------- #
class _SpyPublisher:
    def __init__(self):
        self.payloads: list[dict] = []

    def publish_payload(self, p):
        self.payloads.append(p)


class _FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx") and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.mark.asyncio
async def test_zero_balance_short_circuits_before_llm(monkeypatch):
    """⚠️ ГЛАВНОЕ ПРО ДЕНЬГИ: баланс исчерпан → запрос НЕ идёт в LLM.

    Проверяем, что при `has_sufficient_credits=False` резерв возвращает short-circuit
    (result != None) и НЕ выдаёт reservation_id — то есть прогон не начнётся.
    """
    reserve_called = {"n": 0}

    class _Billing:
        def __init__(self, *a, **k):
            pass

        async def has_sufficient_credits(self, user_id):
            return False  # баланс исчерпан

        async def reserve(self, *a, **k):
            reserve_called["n"] += 1
            return "should-not-happen"

    import service.services.billing.application.billing_service as bs
    import service.services.billing.persistence.billing_repository as br

    monkeypatch.setattr(bs, "BillingService", _Billing)
    monkeypatch.setattr(br, "BillingRepository", lambda *a, **k: None)
    monkeypatch.setattr(cwt, "_overlay_billing", lambda *a, **k: _mk_cfg())
    monkeypatch.setattr(cwt, "_persist_chat_turn", _true_async)
    monkeypatch.setattr(cwt, "_update_job_status_with_session", _noop_async)

    publisher = _SpyPublisher()
    result, reservation_id, reserved = await cwt._reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=publisher,
        job_repo=None,
        session=None,
        job_id="j1",
        thread_id="t1",
        text="дорогой запрос",
        user_id="u1",
        selected_model="m",
        context_chars=50_000,
    )

    assert result is not None, "нулевой баланс НЕ заблокировал — запрос уйдёт в LLM бесплатно"
    assert result.get("metadata", {}).get("insufficient_credits") is True
    assert reservation_id is None and reserved == 0
    assert reserve_called["n"] == 0, "дошли до резерва, хотя баланс уже 0 — лишняя работа"
    assert any(p.get("type") == "agent_reply" for p in publisher.payloads), (
        "пользователю не отдано сообщение об исчерпанном балансе"
    )


@pytest.mark.asyncio
async def test_sufficient_balance_proceeds_to_reserve(monkeypatch):
    """Обратная сторона: есть баланс → идём к резерву, запрос не режется зря."""

    class _Billing:
        def __init__(self, *a, **k):
            pass

        async def has_sufficient_credits(self, user_id):
            return True

        async def reserve(self, *a, **k):
            return "res-123"

    import service.services.billing.application.billing_service as bs
    import service.services.billing.persistence.billing_repository as br

    monkeypatch.setattr(bs, "BillingService", _Billing)
    monkeypatch.setattr(br, "BillingRepository", lambda *a, **k: None)
    monkeypatch.setattr(cwt, "_overlay_billing", lambda *a, **k: _mk_cfg())

    async def _fake_estimate(**k):
        return 100

    monkeypatch.setattr(cwt, "_estimate_reservation_credits", _fake_estimate)

    result, reservation_id, reserved = await cwt._reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=_SpyPublisher(),
        job_repo=None,
        session=None,
        job_id="j1",
        thread_id="t1",
        text="вопрос",
        user_id="u1",
        selected_model="m",
    )

    assert result is None, "запрос заблокирован при достаточном балансе"
    assert reservation_id == "res-123" and reserved == 100


@pytest.mark.asyncio
async def test_expensive_estimate_requires_explicit_confirmation(monkeypatch):
    """Крупный запуск останавливается до reserve/LLM и возвращает повторно нажимаемую кнопку."""
    reserve_called = {"n": 0}

    class _Billing:
        def __init__(self, *a, **k):
            pass

        async def has_sufficient_credits(self, user_id):
            return True

        async def reserve(self, *a, **k):
            reserve_called["n"] += 1
            return "must-not-reserve"

    import service.services.billing.application.billing_service as bs
    import service.services.billing.persistence.billing_repository as br

    monkeypatch.setattr(bs, "BillingService", _Billing)
    monkeypatch.setattr(br, "BillingRepository", lambda *a, **k: None)
    monkeypatch.setattr(cwt, "_overlay_billing", lambda *a, **k: _mk_cfg())
    monkeypatch.setattr(cwt, "_estimate_reservation_credits", lambda **k: _value_async(5_001))
    monkeypatch.setattr(cwt, "_persist_chat_turn", _true_async)
    monkeypatch.setattr(cwt, "_update_job_status_with_session", _noop_async)

    publisher = _SpyPublisher()
    result, reservation_id, reserved = await cwt._reserve_credits_or_short_circuit(
        pg_connector=None,
        config=None,
        publisher=publisher,
        job_repo=None,
        session=None,
        job_id="j1",
        thread_id="t1",
        text="изучи архив",
        user_id="u1",
        selected_model="m",
        redis_client=_FakeRedis(),
    )

    assert result["metadata"]["expensive_run_confirmation_required"] is True
    assert result["metadata"]["mode_offer"]["mode"] == "expensive_run"
    assert result["metadata"]["mode_offer"]["estimated_credits"] == 5_001
    assert result["metadata"]["mode_offer"]["reason_code"] == "confirmation_required"
    assert "reason" not in result["metadata"]["mode_offer"]
    assert "prompt" not in result["metadata"]["mode_offer"]
    assert reservation_id is None and reserved == 0 and reserve_called["n"] == 0
    assert any(p.get("type") == "status_update" for p in publisher.payloads)


async def _value_async(value):
    return value


async def _noop_async(*a, **k):
    return None


async def _true_async(*a, **k):
    return True


def _mk_cfg():
    class _C:
        insufficient_credits_message = "Недостаточно кредитов. Пополните баланс."

    return _C()
