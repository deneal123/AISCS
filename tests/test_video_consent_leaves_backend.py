"""Согласие на просмотр ролика уезжает в сайдкар, а не теряется на границе.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Ссылка на YouTube, нажата кнопка «посмотреть ролик»
(`watch_video: true` в сообщении) — ответ пришёл такой:

    Я не могу просматривать видео с YouTube… _⚠️ Режим «просмотр видео» не запускался._
    списано: 678 кредитов
    логи сайдкара video: только GET /health

Признак ставился нажатием кнопки, доезжал до `session_data`, оттуда — в `engine_env`, и
терялся ровно на границе с сайдкаром: тело `/run` собирается фильтром «только поля
контракта» (`{k: v for k, v in kwargs.items() if k in AgentRunInput.model_fields}`), а
такого поля в контракте не было. Всё остальное выбрасывается МОЛЧА — ни ошибки, ни лога.

Способность включена в проде и стоит в прайсе; на HTTP-движке (основной режим) она была
мертва целиком: кнопка нажималась, ход тарифицировался, ролик не смотрел никто.

⚠️ Тот же класс уже ловили на HTTP-ручке чата — она «объявляла `file_ids` и `watch_video`
и молча их выбрасывала». Объявление поля в ОДНОМ слое ничего не доказывает.
"""

from __future__ import annotations

import pytest

from service.infrastructure.agents_client.contracts.run import AgentRunInput
from service.services.chat.infrastructure.chat_worker.engine_env import build_engine_env


def test_the_contract_carries_the_consent():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ РАЗРЫВ: поля не было в контракте, и фильтр тела
    выбрасывал согласие без единого следа."""
    assert "video_tool_enabled" in AgentRunInput.model_fields


def test_the_filter_keeps_it_in_the_request_body():
    """🔴 ПРОВЕРЯЕМ ИМЕННО ФИЛЬТР, а не наличие поля: тело собирается по
    `model_fields`, и это ровно то место, где признак исчезал."""
    kwargs = {
        "text": "посмотри ролик",
        "thread_id": "t-1",
        "video_tool_enabled": True,
        "нет_такого_поля": "выбрасывается",
    }

    body = AgentRunInput(**{k: v for k, v in kwargs.items() if k in AgentRunInput.model_fields})

    assert body.model_dump(mode="json")["video_tool_enabled"] is True


def test_without_consent_the_body_says_no():
    """🔴 ГРАНИЦА, И ОНА ПРО ДЕНЬГИ. Просмотр — сотня кадров, переезжающих в контекст
    каждого следующего сообщения треда. По умолчанию выключено."""
    body = AgentRunInput(text="привет", thread_id="t-1")

    assert body.model_dump(mode="json")["video_tool_enabled"] is False


@pytest.mark.asyncio
async def test_the_env_derives_the_flag_from_this_message():
    """🔴 СОГЛАСИЕ ИЗ ЭТОГО СООБЩЕНИЯ, А НЕ ИЗ НАСТРОЙКИ ТРЕДА: «включил один раз —
    смотрит всегда» означало бы, что человек согласился однажды, а платит за каждый ход.
    """
    env_yes = await build_engine_env(
        redis_client=None, thread_id="t-1", user_id="u-1", session_data={"watch_video": True}
    )
    env_no = await build_engine_env(
        redis_client=None, thread_id="t-1", user_id="u-1", session_data={}
    )

    assert env_yes["video_tool_enabled"] is True
    assert env_no["video_tool_enabled"] is False
