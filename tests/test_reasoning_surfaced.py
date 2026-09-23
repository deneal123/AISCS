"""Рассуждение модели доезжает до трейса.

🔴 ЖИВОЙ ВОПРОС: «почему в трейсах нигде нет информации о reasoning?». Замер по коду:
слово `reasoning` не встречалось в сайдкаре НИ РАЗУ. Единственное, что доезжало до
панели, — теги `<think>…</think>` из ТЕЛА ответа, которые разбирал фронт. Модели,
отдающие рассуждение отдельным полем — а это все нынешние reasoning-модели через
OpenRouter (`delta.reasoning`) и DeepSeek-совместимые (`delta.reasoning_content`), —
показывали пустую панель, хотя рассуждали и брали за это деньги.

⚠️ Рассуждение НЕ отдаётся дельтами наружу: генератор по контракту выдаёт текст ответа, и
подмешать туда размышления значило бы напечатать их в пузыре чата. Идёт боковым каналом
(`usage_out`) — там же, где `finish_reason` и `tool_calls`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain.client.calls import streaming as streaming_mod
from service.domain.runners import chat_run as chat_runner
from service.domain.subagents.general import GeneralAgent
from service.events import EventType
from service.schemas.agents import UserContext


def _delta(**kw):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(**kw), finish_reason=None)]
    )


def _usage_chunk(reasoning_tokens=None):
    details = (
        SimpleNamespace(reasoning_tokens=reasoning_tokens) if reasoning_tokens is not None else None
    )
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=40,
            total_tokens=50,
            completion_tokens_details=details,
        ),
    )


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


def _client(chunks):
    async def _create(**_kw):
        return _FakeStream(chunks)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))


async def _drain(chunks, usage):
    from service.domain.client.protocol import ProviderRoundState

    state = ProviderRoundState()
    out = []
    async for delta in streaming_mod._stream_one_provider(
        _client(chunks),
        "openrouter",
        [{"role": "user", "content": "q"}],
        "deepseek/deepseek-r1",
        temperature=None,
        max_tokens=None,
        round_state=state,
        include_usage=True,
        tools=None,
        tool_choice=None,
    ):
        out.append(delta)
    usage.update(state.compatibility_payload())
    return "".join(out)


@pytest.mark.asyncio
async def test_openrouter_reasoning_field_is_captured():
    """🔴 ГЛАВНОЕ: `delta.reasoning` больше не теряется."""
    usage: dict = {}
    text = await _drain(
        [
            _delta(reasoning="Сначала проверю условие", content=None),
            _delta(reasoning=", потом посчитаю", content=None),
            _delta(content="Ответ: 42"),
            _usage_chunk(),
        ],
        usage,
    )

    assert text == "Ответ: 42", "рассуждение протекло в текст ответа — оно попадёт в пузырь чата"
    assert usage["reasoning"] == "Сначала проверю условие, потом посчитаю"


@pytest.mark.asyncio
async def test_deepseek_reasoning_content_is_captured():
    """Второе имя того же поля: «поддержим популярное» = «у половины моделей не работает»."""
    usage: dict = {}
    await _drain(
        [_delta(reasoning_content="Думаю"), _delta(content="Готово"), _usage_chunk()], usage
    )

    assert usage["reasoning"] == "Думаю"


@pytest.mark.asyncio
async def test_reasoning_tokens_are_reported():
    """Видимость, а не деньги: это ПОДМНОЖЕСТВО completion, счёт и раньше был верным."""
    usage: dict = {}
    await _drain([_delta(content="ok"), _usage_chunk(reasoning_tokens=31)], usage)

    assert usage["reasoning_tokens"] == 31
    assert usage["completion"] == 40, "reasoning не должен подменять или дополнять completion"


@pytest.mark.asyncio
async def test_reasoning_is_capped():
    """У reasoning-моделей рассуждение бывает в разы длиннее ответа — вниз оно не едет."""
    usage: dict = {}
    await _drain([_delta(reasoning="ф" * 500) for _ in range(40)] + [_usage_chunk()], usage)

    assert len(usage["reasoning"]) <= streaming_mod._MAX_REASONING_CHARS


@pytest.mark.asyncio
async def test_no_reasoning_leaves_the_channel_clean():
    """Обычная модель не рассуждает — пустого ключа быть не должно, иначе панель врёт."""
    usage: dict = {}
    await _drain([_delta(content="привет"), _usage_chunk()], usage)

    assert "reasoning" not in usage


# --------------------------------------------------------------------------- #
# Событие трейса                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reasoning_becomes_a_trace_event(monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА: собранное рассуждение обязано уехать СОБЫТИЕМ.

    ⚠️ Мало прочитать поле в транспорте: если потребитель его не заберёт, все тесты выше
    останутся зелёными, а панель — пустой, ровно как до починки.
    """

    async def _fake_stream(*, messages, model, round_state=None, **_kw):
        yield "Ответ"
        if round_state is not None:
            round_state.update(
                {
                    "prompt": 10,
                    "completion": 40,
                    "total": 50,
                    "model": model,
                    "reasoning": "Проверил условие, посчитал",
                    "reasoning_tokens": 31,
                }
            )

    monkeypatch.setattr(chat_runner, "stream_chat_completion", _fake_stream)

    events = []
    async for event in GeneralAgent({"model": "m"})._run_chat_streamed(
        "вопрос", UserContext(user_id="", request_time=datetime.now(UTC))
    ):
        events.append(event)

    thinking = [
        e
        for e in events
        if e.type == EventType.STATUS_UPDATE and (e.metadata or {}).get("kind") == "reasoning"
    ]
    assert thinking, "рассуждение прочитано, но наружу не отдано — панель снова пуста"
    assert thinking[0].data == "Проверил условие, посчитал"
    assert thinking[0].metadata["reasoning_tokens"] == 31

    # И оно НЕ должно оказаться в тексте ответа.
    text = "".join(e.data for e in events if e.type == EventType.STREAM_CHUNK)
    assert "Проверил условие" not in text
