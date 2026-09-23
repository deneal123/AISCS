"""Артефакт едет РОВНО ОДИН РАЗ, сколько бы чанков ни было в ответе.

⚠️ Почему баг жил незамеченным. Все тестовые дублёры под-агентов отдавали ровно один
``STREAM_CHUNK``, а дефект проявляется начиная со второго: ``stream_text_chunks``
копировала переданную ``metadata`` в КАЖДЫЙ чанк. Презентацию отдают именно так — с
``{"pptx_b64": …}``, — а текст на 5-7 слайдов заведомо длиннее ``chunk_size=220``.

Наблюдаемое следствие в мульти-интенте: сборщик кладёт артефакт из каждого события,
воркер персистит каждый — пользователь получал 2-3 ОДИНАКОВЫХ файла за одну генерацию.
На одиночном маршруте тот же base64 просто ехал по проводу 2-3 раза.

Поэтому здесь текст заведомо многочанковый — иначе тест слеп ровно к тому, что
проверяет.
"""

from __future__ import annotations

import pytest

from service.domain.pipeline.execution_plan import _ARTIFACT_META_KEYS
from service.domain.subagents.base import BaseSubAgent
from service.events import EventType


class _Agent(BaseSubAgent):
    def __init__(self):
        super().__init__(name="t", instructions="i", model_settings={"model": "gpt-4o-mini"})

    async def process(self, user_input, context):  # pragma: no cover — не используется
        yield self.start_event("x")


_ARTIFACT = {"pptx_b64": "UEsDBBQ", "filename": "presentation.pptx"}
# Гарантированно больше одного чанка при chunk_size=220.
_LONG_REPLY = "Слайд с содержательным текстом про квартальные результаты. " * 40


@pytest.mark.asyncio
async def test_artifact_metadata_rides_only_on_the_first_chunk():
    agent = _Agent()

    events = [e async for e in agent.stream_text_chunks(_LONG_REPLY, metadata=_ARTIFACT)]

    assert len(events) > 1, "текст оказался одночанковым — тест слеп к самому дефекту"

    carriers = [e for e in events if (e.metadata or {}).get("pptx_b64")]
    assert len(carriers) == 1, f"артефакт уехал {len(carriers)} раз(а) вместо одного"
    assert carriers[0] is events[0], "артефакт висит не на первом чанке"


@pytest.mark.asyncio
async def test_no_artifact_key_survives_on_later_chunks():
    """Ни один из ключей, по которым собираются артефакты, не должен повторяться."""
    agent = _Agent()

    events = [e async for e in agent.stream_text_chunks(_LONG_REPLY, metadata=_ARTIFACT)]

    for i, event in enumerate(events[1:], start=1):
        leaked = set(event.metadata or {}) & set(_ARTIFACT_META_KEYS)
        assert not leaked, f"чанк {i} снова несёт артефактные ключи: {leaked}"


@pytest.mark.asyncio
async def test_text_is_still_delivered_whole():
    """⚠️ Склейка чанков обязана остаться исходником — иначе «починка» съела бы ответ."""
    agent = _Agent()

    events = [e async for e in agent.stream_text_chunks(_LONG_REPLY, metadata=_ARTIFACT)]

    assert "".join(str(e.data or "") for e in events) == _LONG_REPLY
    assert all(e.type == EventType.STREAM_CHUNK for e in events)
