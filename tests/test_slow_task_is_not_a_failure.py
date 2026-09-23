"""Задача исполняется дольше ожидания — это НЕ «очередь недоступна».

⚠️ ЖИВОЙ ПРОГОН. Сообщение с PDF-техзаданием ушло в 13:38:50; ожидание результата в
веб-процессе сдалось через 30 секунд, а воркер спокойно доработал и записал настоящий
ответ на 6 403 токена. Пользователь при этом получил «Сервис временно перегружен», а в
тред — ПОВЕРХ готового ответа — дописались дубль его же вопроса и это ложное сообщение:

    530 user      Что это за документ и что требуется от исполнителя?
    531 assistant 1. **Описание документа**: Это пошаговый план автоматизации…   ← настоящий
    532 user      Что это за документ и что требуется от исполнителя?            ← дубль
    533 assistant Сервис временно перегружен…                                    ← ложь

Причина — в том, что `JobOrchestrationError` смешивал два разных мира. `JobEnqueueError`
и `JobCreationError` значат «задачу поставить не удалось»: отвечать некому, ход не
сохранён, fallback обязан и ответить, и сохранить. `JobExecutionError` значит «задача
ПОСТАВЛЕНА и исполняется»: воркер доведёт её до конца, сохранит ход сам и спишет деньги —
и любое сохранение в веб-процессе тут даёт дубль, а любой отказ ложится поверх успешно
выполненной и оплаченной работы.

Отсюда инвариант: **владелец персиста определяется тем, поставлена ли задача, а не тем,
дождались ли мы её.**
"""

from __future__ import annotations

import pytest

from service.services.chat.domain.chat_contracts import ChatRequestContext, ChatRouteDecision
from service.services.chat.domain.chat_exceptions import JobEnqueueError, JobExecutionError
from service.services.chat.domain.chat_service import ChatService


class _Routing:
    async def resolve_route(self, **kwargs):
        return ChatRouteDecision(selected_model="m")


class _Orchestrator:
    def __init__(self, exc):
        self._exc = exc

    async def execute(self, **kwargs):
        raise self._exc


class _Persistence:
    def __init__(self):
        self.persisted: list[tuple] = []

    async def persist_messages(self, thread_id, text, reply, user_id, user_metadata=None):
        self.persisted.append((thread_id, text, reply, user_id))


class _Fallback:
    def __init__(self):
        self.calls = 0

    async def execute(self, **kwargs):
        from service.services.chat.domain.chat_contracts import (
            ChatProcessingMetadata,
            ChatReplyResult,
        )

        self.calls += 1
        return ChatReplyResult(
            reply="Сервис временно перегружен и не может обработать сообщение.",
            thread_id=str(kwargs.get("thread_id")),
            metadata=ChatProcessingMetadata(data={"degraded": True}),
        )


def _service(exc):
    persistence = _Persistence()
    fallback = _Fallback()
    service = ChatService(_Routing(), _Orchestrator(exc), persistence, fallback)
    return service, persistence, fallback


def _context():
    return ChatRequestContext(thread_id="t-1", text="Проанализируй документ", user_id="u-1")


@pytest.mark.asyncio
async def test_slow_task_does_not_duplicate_the_turn():
    """⚠️ ГЛАВНОЕ. Задача исполняется → веб-процесс НИЧЕГО не сохраняет.

    Ход сохранит воркер, в своей транзакции. Сохранение здесь и дало те самые строки
    532/533 поверх настоящего ответа.
    """
    service, persistence, _ = _service(JobExecutionError("Failed waiting for chat task result"))

    await service.post_message(_context())

    assert persistence.persisted == [], (
        "веб-процесс сохранил ход, хотя задача исполняется и воркер сохранит его сам — "
        f"в треде появится дубль вопроса и лишний ответ: {persistence.persisted}"
    )


@pytest.mark.asyncio
async def test_slow_task_is_not_reported_as_overload():
    """Пользователю не врут: работа идёт, а не «сервис перегружен».

    Разница практическая: на «перегружен» пользователь отправляет сообщение заново —
    это второй платный прогон поверх первого, который вот-вот ответит.
    """
    service, _, fallback = _service(JobExecutionError("Failed waiting for chat task result"))

    result = await service.post_message(_context())

    assert fallback.calls == 0, "позван общий fallback — он и приносит текст про перегрузку"
    assert "перегружен" not in result.reply, f"отказ поверх исполняемой задачи: {result.reply!r}"
    assert result.metadata.data.get("reason") == "result_wait_timeout", (
        f"причина деградации не различима в метаданных: {result.metadata.data}"
    )


@pytest.mark.asyncio
async def test_unqueued_task_still_falls_back_and_persists():
    """⚠️ Обратная сторона: «задачу не поставили» обязано работать КАК ПРЕЖДЕ.

    Иначе, разведя случаи, легко потерять единственный путь, где ответ и сохранение
    действительно лежат на веб-процессе, — и сообщение пропадёт бесследно.
    """
    service, persistence, fallback = _service(JobEnqueueError("Failed to enqueue chat task"))

    result = await service.post_message(_context())

    assert fallback.calls == 1, "очередь недоступна, а fallback не позван — отвечать некому"
    assert persistence.persisted, "ход не сохранён никем: воркера нет, веб-процесс промолчал"
    assert "перегружен" in result.reply
