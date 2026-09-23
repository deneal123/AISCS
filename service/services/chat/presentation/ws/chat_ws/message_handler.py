import asyncio
import time

from service.services.chat.application.use_cases.ws_message_use_case import (
    HandleWsChatMessageUseCase,
)
from service.services.chat.presentation.error_mapper import map_to_ws_error_payload
from service.services.chat.presentation.ws.chat_ws.metrics import ChatWsMetrics
from service.services.chat.presentation.ws.chat_ws.payload_builder import ChatWsPayloadBuilder
from service.services.chat.presentation.ws.chat_ws.temp_files import TempFilesManager


class ChatMessageHandler:
    def __init__(
        self,
        job_service,
        file_service,
        metrics: ChatWsMetrics,
        chat_service,
        redis_client=None,
        rate_limiter=None,
        rate_limits: dict | None = None,
    ) -> None:
        self._job_service = job_service
        self._file_service = file_service
        self._metrics = metrics
        self._chat_service = chat_service
        self._redis_client = redis_client
        self._rate_limiter = rate_limiter
        self._rate_limits = rate_limits or {}

    async def _is_rate_limited(self, websocket, msg: dict, session: dict) -> bool:
        """Анти-флуд: проверка частоты ДО создания джоба (минует fallback)."""
        if self._rate_limiter is None:
            return False
        result = await self._rate_limiter.check(
            identity=session.get("user_id"), limits=self._rate_limits, now=time.time()
        )
        if result.allowed:
            return False
        await websocket.send_json(
            {
                "type": "error",
                "code": "rate_limited",
                "retry_after": result.retry_after,
                "message": "Слишком много запросов. Подождите немного.",
                "message_id": msg.get("id"),
            }
        )
        return True

    async def handle_incoming_messages(
        self,
        websocket,
        thread_id: str,
        session: dict,
        consumer_task: asyncio.Task,
        heartbeat_task: asyncio.Task,
    ) -> None:
        try:
            while True:
                try:
                    msg = await websocket.receive_json()
                except Exception:
                    break

                self._metrics.inc("messages_received_total")
                if msg.get("type") == "message":
                    await self._handle_chat_message(websocket, thread_id, msg, session)
                elif msg.get("type") == "compact_context":
                    await self._handle_compact_context(websocket, thread_id, session)
        finally:
            consumer_task.cancel()
            heartbeat_task.cancel()
            for task in (consumer_task, heartbeat_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await TempFilesManager.cleanup_temp_files(session, self._file_service)

    async def _handle_compact_context(self, websocket, thread_id: str, session: dict) -> None:
        """Ручная компактизация по клику кольца: сжать диалог → долговременная память
        MemOS, вернуть событие context_compacted (фронт сбрасывает кольцо + рисует divider)."""
        try:
            await websocket.send_json({"type": "compact_started", "thread_id": thread_id})
            from service.services.chat.application.use_cases.compact_context_use_case import (
                CompactContextUseCase,
            )

            result = await CompactContextUseCase().execute(
                thread_id=thread_id, user_id=session.get("user_id")
            )
            await websocket.send_json(
                {"type": "context_compacted", "thread_id": thread_id, **result}
            )
        except Exception as exc:
            await websocket.send_json(map_to_ws_error_payload(exc, message_id=None))

    async def _handle_chat_message(
        self, websocket, thread_id: str, msg: dict, session: dict
    ) -> None:
        if await self._is_rate_limited(websocket, msg, session):
            return
        try:
            file_ids = msg.get("file_ids") if isinstance(msg.get("file_ids"), list) else []
            if file_ids:
                TempFilesManager.register_temp_file_ids(session, file_ids)

            result = await HandleWsChatMessageUseCase(
                self._job_service,
                self._chat_service,
                self._redis_client,
            ).execute(
                thread_id=thread_id,
                msg=msg,
                session=session,
            )
            if result["type"] == "job_created":
                await websocket.send_json(result)
                return

            await websocket.send_json(ChatWsPayloadBuilder.agent_reply_payload(result))
            await websocket.send_json(ChatWsPayloadBuilder.agent_complete_payload(result))
        except Exception as exc:
            await websocket.send_json(map_to_ws_error_payload(exc, message_id=msg.get("id")))
