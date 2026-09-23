"""Согласие на просмотр ролика доходит до инструмента, а не теряется на границе.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Ссылка на YouTube, нажата кнопка «посмотреть ролик» (в теле
запроса `watch_video: true`) — ответ:

    Я не могу просматривать видео с YouTube… _⚠️ Режим «просмотр видео» не запускался._
    списано: 678 кредитов
    логи сайдкара video: только GET /health

Признак жил в схеме контекста (`UserContext.video_tool_enabled`), гейт инструмента его
исправно проверял, backend ставил его в `engine_env` — и на этом всё заканчивалось: тело
`/run` собирается фильтром «только поля контракта», а такого поля в контракте не было.
Всё, что не объявлено, выбрасывается МОЛЧА.

То есть платная способность, включённая в проде и стоящая в прайсе, на HTTP-движке была
мертва целиком: кнопка нажималась, деньги за ход списывались, ролик не смотрел никто.

⚠️ Ровно тот же класс уже ловили на HTTP-ручке чата: она «объявляла `file_ids` и
`watch_video` и молча их выбрасывала». Одно объявление поля в одном слое ничего не значит —
проверять надо ВСЮ цепочку до потребителя.
"""

from __future__ import annotations

import inspect

import pytest

from service.domain.pipeline.processor_flow import build_user_context
from service.schemas.run import AgentRunInput


def test_the_run_body_carries_the_consent():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ РАЗРЫВ: поля не было в теле запроса."""
    assert "video_tool_enabled" in AgentRunInput.model_fields, (
        "согласие снова не поместится в тело /run — фильтр контракта выбросит его молча"
    )

    body = AgentRunInput(thread_id="t-1", text="посмотри ролик", video_tool_enabled=True)

    assert body.to_execute_kwargs()["video_tool_enabled"] is True


def test_the_context_receives_the_consent():
    """🔴 ВТОРОЕ ЗВЕНО. Контекст собирался без признака, и гейт инструмента видел `False`
    даже тогда, когда человек нажал кнопку."""
    context = build_user_context(user_id=1, session=None, thread_id="t-1", video_tool_enabled=True)

    assert context.video_tool_enabled is True


def test_without_consent_the_flag_stays_off():
    """🔴 ГРАНИЦА, И ОНА ПРО ДЕНЬГИ. Просмотр ролика — сотня кадров, переезжающих в
    контекст каждого следующего сообщения. Признак по умолчанию выключен: «включил один
    раз — смотрит всегда» означало бы, что человек согласился однажды, а платит за каждый
    ход."""
    context = build_user_context(user_id=1, session=None, thread_id="t-1")

    assert context.video_tool_enabled is False
    assert AgentRunInput(thread_id="t-1", text="привет").video_tool_enabled is False


def test_the_tool_gate_reads_exactly_this_field():
    """🔴 ТРЕТЬЕ ЗВЕНО. Гейт инструмента и контекст обязаны говорить об ОДНОМ поле:
    переименуй одно из них — и цепочка снова разойдётся молча."""
    from service.domain.tools.video_tool import CONTEXT_ATTR

    context = build_user_context(user_id=1, session=None, thread_id="t", video_tool_enabled=True)

    assert CONTEXT_ATTR in type(context).model_fields, "гейт читает поле, которого в контексте нет"
    assert getattr(context, CONTEXT_ATTR) is True


@pytest.mark.parametrize("consumer", [build_user_context])
def test_every_link_of_the_chain_accepts_it(consumer):
    """⚠️ Сигнатуры на пути: пропусти параметр в любой — и признак снова не доедет.
    Мутации показали, что достаточно одного забытого звена."""
    assert "video_tool_enabled" in inspect.signature(consumer).parameters


def test_the_processor_passes_it_down():
    """🔴 ТОЧКА ВЫЗОВА. Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым
    правка объяснена."""
    import ast

    from service.application import processor

    tree = ast.parse(inspect.getsource(processor.AgentProcessor.process_message_stream).strip())
    passed = [
        kw
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "build_user_context"
        for kw in node.keywords
        if kw.arg == "video_tool_enabled"
    ]

    assert passed, "процессор не передаёт согласие в контекст — гейт снова увидит False"


@pytest.mark.asyncio
async def test_an_already_accepted_offer_is_not_repeated(monkeypatch):
    """🔴 ЗАМЕРЕНО ПОСЛЕ ПОЧИНКИ ЦЕПОЧКИ. Человек нажал кнопку, инструмент отработал —
    сайдкар video ответил на `/watch`, — а карточка предлагалась ЗАНОВО, и ответ получал
    приписку «Режим „просмотр видео“ не запускался». Прямая неправда поверх выполненной
    работы: приписка вешается по наличию предложения, поэтому чинить надо у источника.
    """
    from service.domain.pipeline import auto_mode
    from service.domain.routing.auto_decision import AutoDecision

    monkeypatch.setattr(auto_mode, "_video_offer_allowed", lambda: True)

    # ⚠️ Решатель — провайдерский вызов, в тесте его нет. Без подмены план уходит в
    # обходную ветку («решатель не дал разбираемого ответа»), и предложения не возникает
    # НИ В ОДНОМ случае — тест был бы зелёным, ничего не проверяя.
    async def _decide(*a, **kw):
        return AutoDecision(route="general")

    monkeypatch.setattr(auto_mode, "decide_modes", _decide)

    text = "посмотри https://www.youtube.com/watch?v=aqz-KE-bpKQ"
    agreed = build_user_context(user_id=1, session=None, thread_id="t-1", video_tool_enabled=True)
    fresh = build_user_context(user_id=1, session=None, thread_id="t-1")

    plan_agreed = await auto_mode.resolve_auto_plan(user_input=text, context=agreed)
    plan_fresh = await auto_mode.resolve_auto_plan(user_input=text, context=fresh)

    assert plan_agreed.offered_tool is None, "предложение повторено поверх данного согласия"
    assert plan_fresh.offered_tool == "watch_video", "без согласия предложение обязано быть"


# --- кадры записываются, чем бы контекст ни оказался --------------------------------------- #


def test_frames_are_recorded_into_a_dict_context():
    """🔴 ЗАМЕРЕНО НА ЖИВОМ ПРОГОНЕ, И ЭТО ЛОМАЛО ВСЁ. С подтверждённым согласием сайдкар
    отдал кадры, а инструмент упал:

        Tool 'watch_video' failed: 'dict' object has no attribute 'watched_frames'
        and no __dict__ for setting new attributes

    Человек читал «не удалось посмотреть ролик» при живом сайдкаре и скачанных кадрах.
    Контекст на этом пути — СЛОВАРЬ (плоская копия), и соседний `workspace_tools._ref`
    читает обе формы по той же причине.
    """
    from service.domain.tools.video_tool import _remember_frames

    context: dict = {}
    _remember_frames(context, [{"t_sec": 0.0}])
    _remember_frames(context, [{"t_sec": 1.0}])

    assert [f["t_sec"] for f in context["watched_frames"]] == [0.0, 1.0]


def test_frames_are_recorded_into_an_object_context():
    """🔴 ГРАНИЦА: объектный контекст работал и обязан работать дальше."""
    from types import SimpleNamespace

    from service.domain.tools.video_tool import _remember_frames

    context = SimpleNamespace()
    _remember_frames(context, [{"t_sec": 2.0}])

    assert context.watched_frames == [{"t_sec": 2.0}]


def test_an_unwritable_context_does_not_kill_the_tool():
    """⚠️ Просмотр СОСТОЯЛСЯ, описание собрано — ронять инструмент из-за того, что кадры
    некуда положить, значит терять и работу, и деньги за неё."""
    from service.domain.tools.video_tool import _remember_frames

    class _Frozen:
        __slots__ = ()

    _remember_frames(_Frozen(), [{"t_sec": 3.0}])  # не должно бросить
