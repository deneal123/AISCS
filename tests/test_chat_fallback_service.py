"""Деградация чата при недоступной очереди задач.

Раньше здесь проверялся in-process прогон агента: подменялся ChatAgent, сверялись ответ
и метаданные. Этот путь удалён — и не только потому, что домен уехал в сайдкар.
Собственный комментарий прежней реализации признавал: «здесь пока НЕ тарифицируется —
при недоступности воркера запросы обслуживаются бесплатно (утечка выручки)». То есть
падение celery превращалось в бесплатную раздачу LLM-ответов.

Теперь проверяем противоположное свойство: сервис ЧЕСТНО отказывает и ничего не считает.
"""

import pytest

from service.services.chat.domain.chat_fallback_service import ChatFallbackService

_ARGS = dict(
    thread_id="t1",
    text="привет",
    user_id="7",
    selected_model=None,
    input_type=None,
    web_search=False,
    deep_research=False,
    file_context="",
    route_override=None,
)


@pytest.mark.asyncio
async def test_returns_honest_unavailable_reply() -> None:
    """Пользователю говорят, что сервис занят, а не выдают ответ бесплатно."""
    result = await ChatFallbackService().execute(**_ARGS)

    assert result.thread_id == "t1"
    assert "временно" in result.reply.lower()
    assert result.metadata.data["degraded"] is True
    assert result.metadata.data["reason"] == "job_queue_unavailable"


@pytest.mark.asyncio
async def test_does_not_call_any_agent() -> None:
    """Главное свойство: никакого исполнения. Прежний путь звал ChatAgent прямо в
    веб-процессе — именно он и раздавал бесплатные ответы."""

    class _Boom:
        async def handle_message(self, *a, **kw):
            raise AssertionError("деградация не должна исполнять агента")

    result = await ChatFallbackService(agent=_Boom()).execute(**_ARGS)

    assert result.metadata.data["degraded"] is True


@pytest.mark.asyncio
async def test_tool_flags_do_not_open_a_second_path() -> None:
    """Раньше флаги инструментов уводили в отдельную ветку _tool_path — тоже
    бесплатную. Теперь любой набор флагов даёт один и тот же честный отказ."""
    result = await ChatFallbackService().execute(
        **{**_ARGS, "web_search": True, "deep_research": True, "attachments": [{"kind": "image"}]}
    )

    assert result.metadata.data["reason"] == "job_queue_unavailable"
