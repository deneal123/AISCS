"""Инструмент просмотра видео: заперт деньгами, честен про то, чего не видел.

🔴 Он ДОРОГОЙ и вызывается МОДЕЛЬЮ посреди прогона — спросить в этот момент уже некого.
Поэтому проверяем не «работает ли», а три вещи, каждая из которых стоит денег или доверия:
запор признаком, честность про пропуски и то, что мегабайты кадров не уезжают в переписку.
"""

from __future__ import annotations

import json

import pytest

from service.domain.capabilities.agent_spec import COST_EXPENSIVE
from service.domain.capabilities.tools.registry import resolve_toolset, tool_specs
from service.domain.capabilities.tools.spec import NEEDS_CONFIRMATION
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
async def test_empty_source_is_unbilled_not_a_successful_view(sidecar, monkeypatch):
    from unittest.mock import AsyncMock

    from service.domain.tools import unbilled_calls
    from service.infrastructure import video_stt

    sidecar({"duration_sec": 10, "transcript": [], "frames": []})
    fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(video_stt, "acquire_local_transcript", fallback)
    with unbilled_calls.collect() as billing:
        outcome = await video_tool.watch_video_tool(
            _Wrapper(_Ctx()), json.dumps({"url": "https://v/1"})
        )
    assert outcome.status == "failed" and not outcome.billable
    assert outcome.failure_code == "unavailable"
    assert billing["waived"] == {"watch_video": 1}
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_accepted_numeric_text_timestamps_are_renderable(sidecar):
    sidecar({"duration_sec": "10", "transcript": [{"t_sec": "2.5", "text": "speech"}]})
    outcome = await video_tool.watch_video_tool(
        _Wrapper(_Ctx()), json.dumps({"url": "https://v/1"})
    )
    assert isinstance(outcome, str) and "speech" in outcome


@pytest.mark.asyncio
async def test_unknown_sidecar_warning_is_not_echoed_to_model(sidecar, caplog):
    sidecar(
        {
            "duration_sec": 10,
            "transcript": [{"t_sec": 0, "text": "speech"}],
            "warnings": ["PRIVATE-PROXY-BODY"],
        }
    )
    outcome = await video_tool.watch_video_tool(
        _Wrapper(_Ctx()), json.dumps({"url": "https://v/1"})
    )
    assert isinstance(outcome, str)
    assert "PRIVATE" not in outcome + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize(
    "transcript",
    [
        "PRIVATE-SOURCE",
        {"text": "PRIVATE-SOURCE"},
        0,
        [{"t_sec": False, "text": "PRIVATE-SOURCE"}],
        [{"t_sec": 0, "text": "PRIVATE-SOURCE\ud800"}],
    ],
    ids=["scalar", "mapping", "falsey-scalar", "boolean-time", "invalid-unicode"],
)
async def test_malformed_source_is_typed_before_frames_or_artifacts(
    sidecar, caplog, monkeypatch, scoped, transcript
):
    from contextlib import nullcontext

    from service.domain.execution.context import PrivateRunResources, use_run_execution
    from service.domain.runners.tool_runtime.contracts import ToolCallOutcome
    from service.domain.video_summary.source import SOURCE_KEY, VideoTranscript

    sidecar(
        {
            "duration_sec": 10,
            "transcript": transcript,
            "frames": [{"t_sec": 0, "image_b64": "PRIVATE-FRAME"}],
        }
    )
    context = _Ctx()
    if not scoped:
        monkeypatch.setattr("service.domain.execution.context.current_execution", lambda: None)
    scope = use_run_execution(PrivateRunResources()) if scoped else nullcontext()
    with scope as execution:
        outcome = await video_tool.watch_video_tool(
            _Wrapper(context), json.dumps({"url": "https://v/1"})
        )
        assert isinstance(outcome, ToolCallOutcome)
        assert outcome.status == "failed" and not outcome.billable and not outcome.retryable
        assert outcome.failure_code == "protocol"
        assert not getattr(context, "watched_frames", [])
        assert "PRIVATE" not in outcome.text + caplog.text
        if execution is not None:
            assert execution.artifacts.get(SOURCE_KEY, VideoTranscript) is None
            assert execution.usage.billable_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("transcript", [[], [{"t_sec": 0, "text": "accepted speech"}]])
@pytest.mark.parametrize(
    "frames",
    [
        "PRIVATE-FRAME",
        {"image_b64": "PRIVATE-FRAME"},
        False,
        [None],
        [{"t_sec": 0}],
        [{"t_sec": 0, "image_b64": 1}],
        [{"t_sec": float("nan"), "image_b64": "PRIVATE-FRAME"}],
        [{"t_sec": True, "image_b64": "PRIVATE-FRAME"}],
    ],
)
async def test_invalid_frames_fail_before_fallback_or_source_publication(
    sidecar, monkeypatch, caplog, frames, transcript
):
    from unittest.mock import AsyncMock

    from service.domain.execution.context import PrivateRunResources, use_run_execution
    from service.domain.runners.tool_runtime.contracts import ToolCallOutcome
    from service.domain.video_summary.source import SOURCE_KEY, VideoTranscript
    from service.infrastructure import video_stt

    sidecar({"duration_sec": 10, "transcript": transcript, "frames": frames})
    fallback = AsyncMock(return_value=None)
    monkeypatch.setattr(video_stt, "acquire_local_transcript", fallback)
    context = _Ctx()
    with use_run_execution(PrivateRunResources()) as execution:
        outcome = await video_tool.watch_video_tool(
            _Wrapper(context), json.dumps({"url": "https://v/1"})
        )
        assert isinstance(outcome, ToolCallOutcome)
        assert outcome.failure_code == "protocol" and not outcome.billable
        assert not outcome.retryable
        assert not getattr(context, "watched_frames", [])
        assert execution.artifacts.get(SOURCE_KEY, VideoTranscript) is None
        assert "PRIVATE" not in outcome.text + caplog.text
    fallback.assert_not_awaited()


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

    assert text.status == "failed" and not text.billable
    assert "длиннее" in text.text
    assert "не выдумывай" in text.text.lower()


@pytest.mark.asyncio
async def test_a_disabled_sidecar_is_said_out_loud(monkeypatch):
    """Выключенная способность — не повод молчать: молчание модель заполнит выдумкой."""
    monkeypatch.setattr(video_tool, "_client", lambda: None)

    text = await video_tool.watch_video_tool(_Wrapper(_Ctx()), json.dumps({"url": "https://v/1"}))

    assert text.status == "failed" and not text.billable
    assert "недоступ" in text.text.lower() and "не выдумывай" in text.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "failure", "retryable"),
    [
        ("timeout", "timeout", True),
        ("toolchain_failed", "unavailable", True),
        ("too_large", "invalid_arguments", False),
        ("PRIVATE-VIDEO-ERROR", "unavailable", True),
    ],
)
async def test_sidecar_failure_is_typed_unbilled_and_private(
    sidecar, caplog, code, failure, retryable
):
    from service.infrastructure.sidecar import SidecarUnavailable

    sidecar(SidecarUnavailable("video", code, "PRIVATE-PROVIDER-BODY"))
    outcome = await video_tool.watch_video_tool(
        _Wrapper(_Ctx()), json.dumps({"url": "https://v/1"})
    )
    assert outcome.status == "failed" and not outcome.billable
    assert outcome.failure_code == failure
    assert outcome.retryable is retryable
    assert "PRIVATE" not in outcome.text + caplog.text


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
