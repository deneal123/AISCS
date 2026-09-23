"""Инструмент просмотра видео: заперт деньгами, честен про то, чего не видел.

🔴 Он ДОРОГОЙ и вызывается МОДЕЛЬЮ посреди прогона — спросить в этот момент уже некого.
Поэтому проверяем не «работает ли», а три вещи, каждая из которых стоит денег или доверия:
запор признаком, честность про пропуски и то, что мегабайты кадров не уезжают в переписку.
"""

from __future__ import annotations

import json

import pytest

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.tool_registry import resolve_toolset, tool_specs
from service.domain.capabilities.tool_spec import NEEDS_CONFIRMATION
from service.domain.tools import video_tool


def test_the_tool_is_declared_expensive_and_locked():
    """⚠️ ГЛАВНОЕ. Незапертый дорогой инструмент уехал бы модели в каждом прогоне."""
    spec = tool_specs()["watch_video"]

    assert spec.cost_class == COST_EXPENSIVE
    assert spec.confirm_by_default is True
    assert spec.requires_context_attr == video_tool.CONTEXT_ATTR
    assert spec.billing_name == "watch_video", "вызов не тарифицируется — просмотр бесплатен"


def test_without_consent_it_is_withheld_for_money_not_for_data():
    """🔴 Причина отказа — `needs_confirmation`, а не «нет данных»: способность ЕСТЬ и ждёт
    кнопки, а «нет данных» сообщило бы человеку, что делать нечего."""
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    result = resolve_toolset(list(DEFAULT_FUNCTION_TOOLS), context=None)

    reasons = {o.tool: o.reason for o in result.omissions}
    assert reasons.get("watch_video") == NEEDS_CONFIRMATION
    assert "watch_video" not in [t.name for t in result.tools]


def test_with_consent_it_reaches_the_model():
    """🔴 БЕЗ ЭТОГО правило выше зелено и от «никогда не выдавать»."""
    from service.domain.tools.function_tools import DEFAULT_FUNCTION_TOOLS

    class _Ctx:
        video_tool_enabled = True

    result = resolve_toolset(list(DEFAULT_FUNCTION_TOOLS), context=_Ctx())

    assert "watch_video" in [t.name for t in result.tools]


def test_the_result_is_capped_by_nothing_and_that_is_deliberate():
    """⚠️ Обрезанная посередине расшифровка выглядит как оборванная мысль спикера, и
    модель перескажет её как сказанное. Резать нечем — потолок снят намеренно."""
    assert tool_specs()["watch_video"].result_limit_chars is None


class _Ctx:
    video_tool_enabled = True
    context_budget_tokens = 40_000


@pytest.fixture
def sidecar(monkeypatch):
    """Подменяет ответ сайдкара просмотра."""

    def _install(payload: dict | Exception):
        class _Client:
            available = True

            async def request_json(self, *_a, **_kw):
                if isinstance(payload, Exception):
                    raise payload
                return payload

        monkeypatch.setattr(video_tool, "_client", lambda: _Client())

    return _install


class _Wrapper:
    def __init__(self, context):
        self.context = context


@pytest.mark.asyncio
async def test_frames_go_to_the_run_inventory_not_into_the_reply(sidecar):
    """🔴 МЕГАБАЙТЫ НЕ УЕЗЖАЮТ В ПЕРЕПИСКУ. Результат инструмента переотправляется КАЖДЫМ
    следующим раундом: base64 в нём означал бы, что кадры оплачиваются заново на каждом.
    """
    sidecar(
        {
            "title": "Лекция",
            "duration_sec": 600,
            "frames": [{"t_sec": 0, "image_b64": "AAAA"}, {"t_sec": 5, "image_b64": "BBBB"}],
            "frames_examined": 40,
            "transcript": [{"t_sec": 1, "text": "здравствуйте"}],
            "truncated": True,
            "warnings": [],
        }
    )
    context = _Ctx()

    text = await video_tool.watch_video_tool(_Wrapper(context), json.dumps({"url": "https://v/1"}))

    assert "AAAA" not in text and "BBBB" not in text, "кадры уехали в результат инструмента"
    assert len(context.watched_frames) == 2, "кадры не попали в опись прогона — их никто не увидит"


@pytest.mark.asyncio
async def test_it_says_out_loud_that_it_did_not_see_everything(sidecar):
    """🔴 «Посмотрел ролик» и «посмотрел сто кадров из часа» — РАЗНЫЕ утверждения.

    Без этой строки модель отвечает так, будто видела всё, и уверенно описывает то, чего
    в показанных кадрах не было.
    """
    sidecar(
        {
            "duration_sec": 3600,
            "frames": [{"t_sec": 0, "image_b64": "A"}],
            "frames_examined": 900,
            "transcript": [],
            "truncated": True,
            "warnings": [],
        }
    )

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert "НЕ ВСЕ" in text
    assert "не выдумывай" in text.lower(), "без расшифровки модели не сказано молчать о репликах"


@pytest.mark.asyncio
async def test_a_full_view_does_not_carry_the_warning(sidecar):
    """⚠️ Оговорка на КАЖДОМ ответе обесценивает её там, где она нужна."""
    sidecar(
        {
            "duration_sec": 10,
            "frames": [{"t_sec": 0, "image_b64": "A"}],
            "frames_examined": 1,
            "transcript": [{"t_sec": 0, "text": "раз"}],
            "truncated": False,
            "warnings": [],
        }
    )

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert "НЕ ВСЕ" not in text


@pytest.mark.asyncio
async def test_a_refusal_names_its_reason(sidecar):
    """⚠️ «Не смог» без причины модель перескажет как «видео недоступно», а отказ по
    длительности и сбой сети требуют от человека РАЗНОГО."""
    from service.infrastructure.sidecar import SidecarBadRequest

    sidecar(SidecarBadRequest("video", "too_long", "ролик длиннее потолка"))

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert "too_long" in text or "длиннее" in text
    assert "не выдумывай" in text.lower()


@pytest.mark.asyncio
async def test_a_disabled_sidecar_is_said_out_loud(monkeypatch):
    """Выключенная способность — не повод молчать: молчание модель заполнит выдумкой."""
    monkeypatch.setattr(video_tool, "_client", lambda: None)

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert "недоступ" in text.lower() and "не выдумывай" in text.lower()


@pytest.mark.asyncio
async def test_the_real_context_window_is_sent_not_a_constant(sidecar, monkeypatch):
    """🔴 Сайдкар считает бюджет кадров ОТ ОКНА ПРОГОНА. Прислав константу, мы получили бы
    сотню кадров в окне, где помещается десяток, — и вытеснили бы ими переписку."""
    seen: dict = {}

    class _Client:
        available = True

        async def request_json(self, _method, _path, *, json_body=None, **_kw):
            seen.update(json_body or {})
            return {"frames": [], "transcript": [], "frames_examined": 0}

    monkeypatch.setattr(video_tool, "_client", lambda: _Client())

    await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert seen["context_tokens"] == 40_000, "уехало не окно прогона"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (10, "10 с"),
        (59, "59 с"),
        (60, "1 мин"),
        (95, "1 мин 35 с"),
        (600, "10 мин"),
        (3600, "1 ч 00 мин"),
        (5400, "1 ч 30 мин"),
    ],
)
def test_duration_is_readable_at_every_scale(seconds, expected):
    """🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. Минутами всегда — это «длительность 0 мин.» на
    десятисекундном клипе, и модель перескажет это человеку буквально: ответ прочитается
    как поломка там, где всё работает.
    """
    assert video_tool._duration_words(seconds) == expected


@pytest.mark.asyncio
async def test_a_short_clip_is_not_described_as_zero_minutes(sidecar):
    """⚠️ Проверяем в СОБРАННОМ тексте: правило, верное в помощнике, могли не позвать."""
    sidecar(
        {
            "title": "клип",
            "duration_sec": 10,
            "frames": [{"t_sec": 0, "image_b64": "A"}],
            "frames_examined": 1,
            "transcript": [],
            "truncated": False,
            "warnings": [],
        }
    )

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert "0 мин" not in text, "короткий ролик описан нулём минут"
    assert "10 с" in text
