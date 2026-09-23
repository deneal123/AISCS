"""Фаза 3 биллинга: кошельки, баланс, списание (подписка→докупка), гейт.

Логика баланса/списания тестируется без БД (фейковый репозиторий и
FakeDBSession). Реальную SQL-семантику Postgres проверяет прогон миграций
на живой БД (в песочнице её нет).
"""

from datetime import date

import pytest

from service.services.billing.application.billing_service import (
    Balance,
    BillingService,
    month_period,
)
from service.services.billing.persistence.billing_repository import BillingRepository
from tests.test_helpers import FakeConnector, FakeDBSession


class _Cfg:
    free_plan_credits = 10_000


# --------------------------------------------------------------------------- #
# month_period                                                                #
# --------------------------------------------------------------------------- #
def test_month_period_mid_year() -> None:
    assert month_period(date(2026, 6, 26)) == (date(2026, 6, 1), date(2026, 7, 1))


def test_month_period_december_rollover() -> None:
    assert month_period(date(2026, 12, 15)) == (date(2026, 12, 1), date(2027, 1, 1))


# --------------------------------------------------------------------------- #
# BillingService.get_balance / has_sufficient_credits                         #
# --------------------------------------------------------------------------- #
class _FakeRepo:
    def __init__(self, balance_row=None):
        self._row = balance_row
        self.charge_calls = []

    async def get_balance(self, *, user_id):
        return self._row

    async def charge(self, **kwargs):
        self.charge_calls.append(kwargs)
        return {"from_subscription": 0, "from_topup": 0}


@pytest.mark.asyncio
async def test_get_balance_with_active_quota() -> None:
    repo = _FakeRepo(
        {"plan": "free", "topup": 200, "limit": 10000, "used": 3000, "period_end": date(2026, 7, 1)}
    )
    svc = BillingService(repo, _Cfg())
    bal = await svc.get_balance("u1", today=date(2026, 6, 26))
    assert isinstance(bal, Balance)
    assert bal.subscription_remaining == 7000
    assert bal.subscription_limit == 10000
    assert bal.topup == 200
    assert bal.total == 7200
    assert bal.reset_date == date(2026, 7, 1)


@pytest.mark.asyncio
async def test_get_balance_no_quota_uses_free_allowance() -> None:
    repo = _FakeRepo({"plan": "free", "topup": 0, "limit": None, "used": None, "period_end": None})
    svc = BillingService(repo, _Cfg())
    bal = await svc.get_balance("u1", today=date(2026, 6, 26))
    assert bal.subscription_remaining == 10_000  # free allowance (ещё не провизионен)
    assert bal.subscription_limit is None
    assert bal.total == 10_000
    assert bal.reset_date == date(2026, 7, 1)


@pytest.mark.asyncio
async def test_get_balance_user_not_found() -> None:
    svc = BillingService(_FakeRepo(None), _Cfg())
    bal = await svc.get_balance("ghost", today=date(2026, 6, 26))
    assert bal.total == 10_000
    assert bal.topup == 0


@pytest.mark.asyncio
async def test_has_sufficient_credits() -> None:
    rich_row = {"plan": "free", "topup": 0, "limit": 100, "used": 10, "period_end": None}
    broke_row = {"plan": "free", "topup": 0, "limit": 100, "used": 100, "period_end": None}
    rich = BillingService(_FakeRepo(rich_row), _Cfg())
    broke = BillingService(_FakeRepo(broke_row), _Cfg())
    assert await rich.has_sufficient_credits("u1") is True
    assert await broke.has_sufficient_credits("u1") is False


@pytest.mark.asyncio
async def test_charge_passes_period_and_amounts() -> None:
    repo = _FakeRepo()
    svc = BillingService(repo, _Cfg())
    await svc.charge(
        "u1", credits=42, tokens=150, raw_cost_rub=8.5, today=date(2026, 6, 26), metadata={"m": 1}
    )
    assert len(repo.charge_calls) == 1
    call = repo.charge_calls[0]
    assert call["credits"] == 42
    assert call["tokens"] == 150
    assert call["period_start"] == date(2026, 6, 1)
    assert call["period_end"] == date(2026, 7, 1)
    assert call["free_plan_credits"] == 10_000


# --------------------------------------------------------------------------- #
# BillingRepository.get_balance shaping                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_repo_get_balance_shapes_row() -> None:
    session = FakeDBSession(
        first_map={"FROM profile.user": ("free", 200, 10000, 3000, date(2026, 7, 1))}
    )
    repo = BillingRepository(FakeConnector(session))
    out = await repo.get_balance(user_id="u1")
    assert out == {
        "plan": "free",
        "topup": 200,
        "limit": 10000,
        "used": 3000,
        "period_end": date(2026, 7, 1),
    }


# --------------------------------------------------------------------------- #
# BillingRepository.charge — split подписка→докупка                           #
# --------------------------------------------------------------------------- #
def _find(executed, needle):
    return [(s, p) for s, p in executed if needle in s]


@pytest.mark.asyncio
async def test_charge_splits_subscription_then_topup() -> None:
    # ⚠️ Ключ УТОЧНЁН до остатка квоты: широкий "FOR UPDATE" теперь ловит и чтение
    # докуп-кошелька (оно тоже под блокировкой строки, иначе два списания увидели бы один и
    # тот же остаток). Двойник обязан различать два разных запроса, а не отвечать на оба.
    session = FakeDBSession(
        first_map={'"limit" - used': (100,), "topup_credit_balance": (10_000,)}
    )  # остаток подписки = 100
    repo = BillingRepository(FakeConnector(session))

    result = await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
        metadata={"model": "m"},
    )

    assert result == {"from_subscription": 100, "from_topup": 50}
    assert _find(session.executed, "INSERT INTO profile.token_quotas")  # провижининг
    assert _find(session.executed, "UPDATE profile.token_quotas SET used")[0][1]["amt"] == 100
    assert _find(session.executed, "UPDATE profile.user")[0][1]["amt"] == 50
    assert _find(session.executed, "INSERT INTO profile.billing_events")
    assert _find(session.executed, "INSERT INTO profile.usage_daily")
    assert session._committed is True


@pytest.mark.asyncio
async def test_charge_fully_from_subscription() -> None:
    session = FakeDBSession(first_map={'"limit" - used': (500,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    result = await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert result == {"from_subscription": 150, "from_topup": 0}
    assert _find(session.executed, "UPDATE profile.token_quotas SET used")[0][1]["amt"] == 150
    assert _find(session.executed, "UPDATE profile.user") == []  # докупку не трогаем


@pytest.mark.asyncio
async def test_charge_fully_from_topup_when_subscription_empty() -> None:
    # ⚠️ Ключ УТОЧНЁН до остатка квоты: широкий "FOR UPDATE" теперь ловит и чтение
    # докуп-кошелька (оно тоже под блокировкой строки, иначе два списания увидели бы один и
    # тот же остаток). Двойник обязан различать два разных запроса, а не отвечать на оба.
    session = FakeDBSession(first_map={'"limit" - used': (0,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    result = await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert result == {"from_subscription": 0, "from_topup": 150}
    assert _find(session.executed, "UPDATE profile.token_quotas SET used") == []
    assert _find(session.executed, "UPDATE profile.user")[0][1]["amt"] == 150


# --------------------------------------------------------------------------- #
# BillingRepository.reserve / release_reservation — anti-TOCTOU precheck      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_repo_reserve_succeeds_when_balance_sufficient() -> None:
    session = FakeDBSession(
        first_map={
            "FOR UPDATE": (100,),  # остаток подписки
            "topup_credit_balance FROM profile.user": (50,),  # докуп-кошелёк
            "SUM(tokens_reserved)": (0,),  # активных резервов нет
        }
    )
    repo = BillingRepository(FakeConnector(session))
    reservation_id = await repo.reserve(
        user_id="u1",
        credits=120,
        ttl_seconds=600,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert reservation_id is not None
    insert = _find(session.executed, "INSERT INTO profile.token_reservations")
    assert insert and insert[0][1]["amount"] == 120
    assert insert[0][1]["rid"] == reservation_id
    assert session._committed is True


@pytest.mark.asyncio
async def test_repo_reserve_fails_when_balance_insufficient() -> None:
    session = FakeDBSession(
        first_map={
            "FOR UPDATE": (10,),
            "topup_credit_balance FROM profile.user": (5,),
            "SUM(tokens_reserved)": (0,),
        }
    )
    repo = BillingRepository(FakeConnector(session))
    reservation_id = await repo.reserve(
        user_id="u1",
        credits=100,
        ttl_seconds=600,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert reservation_id is None
    assert _find(session.executed, "INSERT INTO profile.token_reservations") == []


@pytest.mark.asyncio
async def test_repo_reserve_subtracts_active_reservations_from_available() -> None:
    # 100 в подписке + 50 в докупе = 150 доступно на бумаге, но 100 уже держит
    # другой конкурентный запрос -> реально доступно только 50, запрос на 60 упадёт.
    session = FakeDBSession(
        first_map={
            "FOR UPDATE": (100,),
            "topup_credit_balance FROM profile.user": (50,),
            "SUM(tokens_reserved)": (100,),
        }
    )
    repo = BillingRepository(FakeConnector(session))
    reservation_id = await repo.reserve(
        user_id="u1",
        credits=60,
        ttl_seconds=600,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert reservation_id is None


@pytest.mark.asyncio
async def test_repo_release_reservation_marks_refunded() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    await repo.release_reservation(reservation_id="r1")
    release = _find(session.executed, "status = 'refunded'")
    assert release and release[0][1]["rid"] == "r1"
    assert session._committed is True


@pytest.mark.asyncio
async def test_repo_charge_with_reservation_id_commits_it() -> None:
    session = FakeDBSession(first_map={'"limit" - used': (500,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
        reservation_id="r1",
    )
    commit = _find(session.executed, "status = 'committed'")
    assert commit and commit[0][1]["rid"] == "r1"


@pytest.mark.asyncio
async def test_repo_charge_without_reservation_id_skips_commit() -> None:
    session = FakeDBSession(first_map={'"limit" - used': (500,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert _find(session.executed, "status = 'committed'") == []


# --------------------------------------------------------------------------- #
# BillingRepository.charge — идемпотентность по idempotency_key (job_id)       #
# защита от двойного списания при редоставке Celery-задачи                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_repo_charge_skips_when_idempotency_key_already_charged() -> None:
    # За этот job уже есть usage-событие -> повторная (редоставленная) задача НЕ
    # должна списывать снова; резерв ЭТОЙ попытки отпускается (не коммитится).
    session = FakeDBSession(
        first_map={
            "FOR UPDATE": (500,),
            "metadata->>'idempotency_key'": (1,),
        }
    )
    repo = BillingRepository(FakeConnector(session))
    result = await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
        reservation_id="r1",
        idempotency_key="job-42",
    )
    assert result.get("idempotent") is True
    # Повторного списания нет.
    assert _find(session.executed, "UPDATE profile.token_quotas SET used") == []
    assert _find(session.executed, "INSERT INTO profile.billing_events") == []
    assert _find(session.executed, "INSERT INTO profile.usage_daily") == []
    # Резерв этой попытки отпущен (refunded), а НЕ закоммичен.
    refunded = _find(session.executed, "status = 'refunded'")
    assert refunded and refunded[0][1]["rid"] == "r1"
    assert _find(session.executed, "status = 'committed'") == []


@pytest.mark.asyncio
async def test_repo_charge_first_time_records_idempotency_key() -> None:
    import json

    # guard SELECT не находит события -> списываем и КЛАДЁМ ключ в metadata,
    # чтобы редоставка нашла его в следующий раз и не задвоила списание.
    session = FakeDBSession(first_map={'"limit" - used': (500,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    await repo.charge(
        user_id="u1",
        credits=150,
        tokens=300,
        raw_cost_rub=12.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
        idempotency_key="job-42",
    )
    event = _find(session.executed, "INSERT INTO profile.billing_events")
    assert event  # списание произошло
    meta = json.loads(event[0][1]["metadata"])
    assert meta["idempotency_key"] == "job-42"


@pytest.mark.asyncio
async def test_repo_charge_without_idempotency_key_does_not_probe() -> None:
    # Обратная совместимость: без ключа гейта нет, проверочный SELECT не идёт.
    session = FakeDBSession(first_map={'"limit" - used': (500,), "topup_credit_balance": (10_000,)})
    repo = BillingRepository(FakeConnector(session))
    await repo.charge(
        user_id="u1",
        credits=10,
        tokens=20,
        raw_cost_rub=1.0,
        free_plan_credits=10_000,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert _find(session.executed, "metadata->>'idempotency_key'") == []
    assert _find(session.executed, "INSERT INTO profile.billing_events")  # списание прошло


# --------------------------------------------------------------------------- #
# BillingService.reserve / release_reservation / charge(reservation_id=...)   #
# --------------------------------------------------------------------------- #
class _FakeReservationRepo:
    def __init__(self, reservation_id="r1"):
        self._reservation_id = reservation_id
        self.reserve_calls = []
        self.release_calls = []
        self.charge_calls = []

    async def reserve(self, **kwargs):
        self.reserve_calls.append(kwargs)
        return self._reservation_id

    async def release_reservation(self, **kwargs):
        self.release_calls.append(kwargs)

    async def charge(self, **kwargs):
        self.charge_calls.append(kwargs)
        return {"from_subscription": 0, "from_topup": 0}


@pytest.mark.asyncio
async def test_service_reserve_passes_period_and_ttl() -> None:
    repo = _FakeReservationRepo()
    svc = BillingService(repo, _Cfg())
    reservation_id = await svc.reserve("u1", credits=42, ttl_seconds=300, today=date(2026, 6, 26))
    assert reservation_id == "r1"
    assert len(repo.reserve_calls) == 1
    call = repo.reserve_calls[0]
    assert call["credits"] == 42
    assert call["ttl_seconds"] == 300
    assert call["period_start"] == date(2026, 6, 1)
    assert call["period_end"] == date(2026, 7, 1)
    assert call["free_plan_credits"] == 10_000


@pytest.mark.asyncio
async def test_service_reserve_returns_none_when_repo_declines() -> None:
    svc = BillingService(_FakeReservationRepo(reservation_id=None), _Cfg())
    assert await svc.reserve("u1", credits=999999) is None


@pytest.mark.asyncio
async def test_service_release_reservation_delegates() -> None:
    repo = _FakeReservationRepo()
    svc = BillingService(repo, _Cfg())
    await svc.release_reservation("r1")
    assert repo.release_calls == [{"reservation_id": "r1"}]


@pytest.mark.asyncio
async def test_service_charge_passes_reservation_id() -> None:
    repo = _FakeReservationRepo()
    svc = BillingService(repo, _Cfg())
    await svc.charge("u1", credits=42, tokens=150, raw_cost_rub=8.5, reservation_id="r1")
    assert repo.charge_calls[0]["reservation_id"] == "r1"


@pytest.mark.asyncio
async def test_service_charge_forwards_idempotency_key() -> None:
    repo = _FakeReservationRepo()
    svc = BillingService(repo, _Cfg())
    await svc.charge("u1", credits=42, tokens=150, raw_cost_rub=8.5, idempotency_key="job-7")
    assert repo.charge_calls[0]["idempotency_key"] == "job-7"


# --------------------------------------------------------------------------- #
# BillingRepository.refund / BillingService.refund — compensating restitution #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_repo_refund_adds_back_to_topup_and_records_event() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    await repo.refund(user_id="u1", credits=75, reason="job_failed_after_charge")
    topup = _find(session.executed, "UPDATE profile.user")
    assert topup and topup[0][1]["amt"] == 75
    event = _find(session.executed, "'refund'")
    assert event and event[0][1]["user_id"] == "u1"
    assert session._committed is True


@pytest.mark.asyncio
async def test_repo_refund_is_noop_for_zero_credits() -> None:
    session = FakeDBSession()
    repo = BillingRepository(FakeConnector(session))
    await repo.refund(user_id="u1", credits=0, reason="noop")
    assert session.executed == []


@pytest.mark.asyncio
async def test_service_refund_delegates() -> None:
    repo = _FakeReservationRepo()
    repo.refund_calls = []

    async def _refund(**kwargs):
        repo.refund_calls.append(kwargs)

    repo.refund = _refund
    svc = BillingService(repo, _Cfg())
    await svc.refund("u1", credits=75, reason="job_failed_after_charge")
    assert repo.refund_calls == [
        {"user_id": "u1", "credits": 75, "reason": "job_failed_after_charge"}
    ]
