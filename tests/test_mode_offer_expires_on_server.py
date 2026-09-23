"""Срок жизни предложения дорогого режима решает СЕРВЕР, а не браузер.

🔴 Предложение висело под ответом вечно: человек либо жал кнопку задним числом — через
час, когда ответ прочитан и не нужен, — либо оно просто мозолило глаза.

🔴 Отсчёт не может жить в браузере: таймер переживают перезагрузкой, второй вкладкой и
сменой системного времени, а на кону тысячи кредитов. Поэтому «просрочено» решается
здесь, на отдаче истории, по серверному `offered_at`.

⚠️ Просроченное предложение НЕ УДАЛЯЕТСЯ: исчезнувшая карточка неотличима от
«предложения не было». Оно остаётся СЛЕДОМ решения, а рычагом быть перестаёт.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import pytest

from service.services.chat.domain.mode_offer import expire_mode_offer

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


def _offer(**over) -> dict:
    base = {
        "mode": "deep_research",
        "label": "глубокое исследование",
        "offered_at": (NOW - timedelta(seconds=5)).isoformat(),
        "expires_in_sec": 30,
    }
    return {"mode_offer": {**base, **over}}


def test_fresh_offer_stays_a_live_lever():
    meta = expire_mode_offer(_offer(), now=NOW)

    assert "expired" not in meta["mode_offer"]


def test_offer_past_its_deadline_is_marked_expired():
    """⚠️ ГЛАВНОЕ. 31-я секунда — уже поздно, и это решает серверный час."""
    meta = expire_mode_offer(_offer(offered_at=(NOW - timedelta(seconds=31)).isoformat()), now=NOW)

    assert meta["mode_offer"]["expired"] is True


def test_expired_offer_is_kept_as_a_trace_of_the_decision():
    """Исчезнувшая карточка неотличима от «предложения не было»."""
    meta = expire_mode_offer(_offer(offered_at=(NOW - timedelta(hours=2)).isoformat()), now=NOW)

    assert meta["mode_offer"]["mode"] == "deep_research"
    assert meta["mode_offer"]["label"] == "глубокое исследование"


def test_offer_without_a_timestamp_is_expired():
    """Живой рычаг из данных неизвестного происхождения опаснее потерянной кнопки.

    Обычный путь запустить режим (селектор в композере) у человека остаётся, а вот
    «бессрочная кнопка» вернулась бы через любую старую запись в БД.
    """
    offer = _offer()
    offer["mode_offer"].pop("offered_at")

    assert expire_mode_offer(offer, now=NOW)["mode_offer"]["expired"] is True


def test_naive_timestamp_is_read_as_utc():
    """Сайдкар мог отдать метку без зоны — сравнивать «наивное» с aware нельзя."""
    naive = (NOW - timedelta(seconds=5)).replace(tzinfo=None).isoformat()

    assert "expired" not in expire_mode_offer(_offer(offered_at=naive), now=NOW)["mode_offer"]


def test_metadata_without_an_offer_is_untouched():
    meta = {"usage": {"total": 10}}

    assert expire_mode_offer(meta, now=NOW) == meta
    assert expire_mode_offer(None, now=NOW) == {}
    assert expire_mode_offer({"mode_offer": {}}, now=NOW) == {"mode_offer": {}}


def test_wired_into_history():
    """⚠️ ТОЧКА ВЫЗОВА. Проверка должна стоять на отдаче истории, а не рядом с ней.

    Мутация «убрать вызов» оставила бы правило зелёным, а кнопку — вечной: после F5
    предложение приезжало бы из БД живым независимо от того, сколько прошло времени.
    """
    from service.services.chat.persistence import chat_persistence_service as cps

    src = inspect.getsource(cps.ChatPersistenceService.get_messages)
    assert "expire_mode_offer(" in src, "история отдаёт предложение без проверки срока"


@pytest.mark.asyncio
async def test_history_marks_a_stale_offer():
    """Сквозная проверка: старая запись приезжает из истории уже просроченной."""
    import json

    from service.services.chat.persistence.chat_persistence_service import ChatPersistenceService

    stale = {
        "mode_offer": {
            "mode": "pptx_gen",
            "offered_at": "2020-01-01T00:00:00+00:00",
            "expires_in_sec": 30,
        }
    }

    class _Repo:
        async def get_thread_pk(self, thread_id):
            return 1

        async def fetch_messages(self, *, thread_pk, limit, offset):
            return [("assistant", "ответ", datetime.now(UTC), stale)]

    out = await ChatPersistenceService(_Repo()).get_messages("t-1")
    offer = out["messages"][0]["metadata"]["mode_offer"]

    assert offer["expired"] is True, "после F5 кнопка воскресла — отсчёт снова только в браузере"
    assert "pptx_gen" in json.dumps(offer), "след решения потерян"
