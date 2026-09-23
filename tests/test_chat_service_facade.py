import pytest

from service.services.chat.domain.chat_contracts import (
    ChatProcessingMetadata,
    ChatReplyResult,
    ChatRequestContext,
    ChatRouteDecision,
)
from service.services.chat.domain.chat_exceptions import JobEnqueueError
from service.services.chat.domain.chat_service import ChatService


class _FakeRoutingService:
    async def resolve_route(self, **kwargs):
        return ChatRouteDecision(selected_model="m1", routing_metadata={"tool": "none"})


class _FakeOrchestration:
    async def execute(self, **kwargs):
        return ChatReplyResult(
            reply="ok", thread_id="t1", metadata=ChatProcessingMetadata(data={"source": "job"})
        )


class _FakePersistence:
    async def persist_messages(
        self, thread_id, user_text, agent_reply, user_id, user_metadata=None
    ):
        pass

    async def create_thread(self, **kwargs):
        return {"thread_id": "t1", "title": None}

    async def get_thread_messages(self, **kwargs):
        return {"thread_id": "t1", "messages": []}

    async def list_threads(self, **kwargs):
        return {"threads": []}

    async def delete_thread(self, thread_id):
        return True


class _FakeFallback:
    async def execute(self, **kwargs):
        return ChatReplyResult(
            reply="fallback", thread_id="t1", metadata=ChatProcessingMetadata(data={})
        )


@pytest.mark.asyncio
async def test_post_message_uses_orchestrator_and_skips_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # На пути джоб-оркестратора ход диалога сохраняет САМ воркер
    # (_persist_chat_turn). ChatService не должен персистить повторно — иначе
    # получаются дубли сообщений в БД (оба слоя неидемпотентны).
    captured = {"persist": False}

    class _Persistence(_FakePersistence):
        async def persist_messages(
            self, thread_id, user_text, agent_reply, user_id, user_metadata=None
        ):
            captured["persist"] = (thread_id, user_text, agent_reply, user_id)
            captured["meta"] = user_metadata

    service = ChatService(
        routing_service=_FakeRoutingService(),
        orchestration_service=_FakeOrchestration(),
        persistence_service=_Persistence(),
        fallback_service=_FakeFallback(),
    )

    result = await service.post_message(ChatRequestContext(thread_id="t1", text="hello", user_id=1))

    assert isinstance(result, ChatReplyResult)
    assert result.reply == "ok"
    assert result.metadata.data["source"] == "job"
    assert result.metadata.data["model_routing"] == {"tool": "none"}
    assert captured["persist"] is False  # воркер уже сохранил ход


@pytest.mark.asyncio
async def test_post_message_fallback_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fallback исполняет ответ in-process и НЕ персистит сам — на этом пути ход
    # должен сохранить именно ChatService.
    captured = {"persist": False}

    class _Persistence(_FakePersistence):
        async def persist_messages(
            self, thread_id, user_text, agent_reply, user_id, user_metadata=None
        ):
            captured["persist"] = (thread_id, user_text, agent_reply, user_id)
            captured["meta"] = user_metadata

    class _FailingOrchestration:
        async def execute(self, **kwargs):
            # ⚠️ Именно «задачу НЕ ПОСТАВИЛИ». Раньше здесь стоял JobExecutionError, но он
            # значит «задача поставлена и исполняется»: там ход сохранит воркер, и персист
            # в веб-процессе даёт ДУБЛЬ (живой прогон: дубль вопроса и ложное «сервис
            # перегружен» поверх готового ответа). Путь fallback выражается ошибкой
            # постановки — см. tests/test_slow_task_is_not_a_failure.py.
            raise JobEnqueueError("boom")

    service = ChatService(
        routing_service=_FakeRoutingService(),
        orchestration_service=_FailingOrchestration(),
        persistence_service=_Persistence(),
        fallback_service=_FakeFallback(),
    )

    result = await service.post_message(ChatRequestContext(thread_id="t1", text="hello", user_id=1))

    assert result.reply == "fallback"
    assert captured["persist"] == ("t1", "hello", "fallback", 1)


@pytest.mark.asyncio
async def test_post_message_fallback_adds_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingOrchestration:
        async def execute(self, **kwargs):
            # ⚠️ Именно «задачу НЕ ПОСТАВИЛИ». Раньше здесь стоял JobExecutionError, но он
            # значит «задача поставлена и исполняется»: там ход сохранит воркер, и персист
            # в веб-процессе даёт ДУБЛЬ (живой прогон: дубль вопроса и ложное «сервис
            # перегружен» поверх готового ответа). Путь fallback выражается ошибкой
            # постановки — см. tests/test_slow_task_is_not_a_failure.py.
            raise JobEnqueueError("boom")

    service = ChatService(
        routing_service=_FakeRoutingService(),
        orchestration_service=_FailingOrchestration(),
        persistence_service=_FakePersistence(),
        fallback_service=_FakeFallback(),
    )

    result = await service.post_message(ChatRequestContext(thread_id="t1", text="hello", user_id=1))

    assert result.reply == "fallback"
    assert result.metadata.data["error_code"] == "job_enqueue_failed"
