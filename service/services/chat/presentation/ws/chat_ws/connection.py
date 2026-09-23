import asyncio
import logging
from datetime import datetime

from fastapi import status

from service.services.chat.presentation.ws.chat_ws.auth import ChatWsAuthService
from service.services.chat.presentation.ws.chat_ws.message_handler import ChatMessageHandler
from service.services.chat.presentation.ws.chat_ws.metrics import ChatWsMetrics
from service.services.chat.presentation.ws.chat_ws.stream_consumer import ChatStreamConsumer

logger = logging.getLogger(__name__)

_ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"


class ChatWsConnectionService:
    def __init__(
        self,
        auth_service: ChatWsAuthService,
        stream_consumer: ChatStreamConsumer,
        message_handler: ChatMessageHandler,
        settings,
        metrics: ChatWsMetrics,
        chat_service=None,
    ) -> None:
        self._auth_service = auth_service
        self._stream_consumer = stream_consumer
        self._message_handler = message_handler
        self._settings = settings
        self._metrics = metrics
        self._chat_service = chat_service

    async def _ensure_thread_owner(self, websocket, thread_id: str, requester_id: str) -> bool:
        if self._chat_service is None:
            return True
        try:
            owner = await self._chat_service.persistence_service.get_thread_owner(thread_id)
        except Exception:
            logger.exception("Failed to resolve thread owner for %s", thread_id)
            return True
        if owner is not None and str(owner) != str(requester_id):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return False
        return True

    async def run(self, websocket, thread_id: str, last_id: str | None = None) -> None:
        session = await self._auth_service.authenticate(websocket)
        if not session:
            return

        requester_id = str(session.get("user_id") or "")
        if requester_id and requester_id != _ANONYMOUS_USER_ID:
            if not await self._ensure_thread_owner(websocket, thread_id, requester_id):
                return

        stream_key = f"chat:{thread_id}:stream"
        group = f"chat:{thread_id}:group"
        consumer = f"ws-consumer-{thread_id}"

        self._metrics.inc("connections_active")
        try:
            await self._stream_consumer.ensure_group(stream_key, group)

            if last_id:
                await self._stream_consumer.handle_replay(websocket, stream_key, last_id)

            is_anonymous = (
                str(session.get("user_id") or "") == "00000000-0000-0000-0000-000000000000"
            )
            if not is_anonymous:
                await self._stream_consumer.handle_pending_messages(
                    websocket, stream_key, group, consumer
                )

            # 🔴 КУРСОР БЕРЁМ ДО ПРИЁМА СООБЩЕНИЙ. Задача-потребитель стартует
            # асинхронно, и её первый `XREAD` со «$» мог случиться уже после того, как
            # клиентское сообщение ушло в работу: события начала прогона (`auto_decision`,
            # `mode_offer`) публиковались в зазор и терялись навсегда. Найдено живым
            # прогоном: в потоке события ЕСТЬ, а в трейсе первых шагов нет.
            cursor = await self._stream_consumer.resolve_cursor(stream_key, True)
            consumer_task = asyncio.create_task(
                self._stream_consumer.consume_events(
                    websocket,
                    stream_key,
                    group,
                    consumer,
                    start_from_latest=True,
                    cursor=cursor,
                )
            )
            heartbeat_task = asyncio.create_task(self._send_heartbeats(websocket))
            await self._message_handler.handle_incoming_messages(
                websocket,
                thread_id,
                session,
                consumer_task,
                heartbeat_task,
            )
        except Exception:
            self._metrics.inc("connection_errors_total")
            raise
        finally:
            self._metrics.dec("connections_active")

    async def _send_heartbeats(self, websocket) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                await asyncio.sleep(self._settings.heartbeat_interval)
                await websocket.send_json(
                    {"type": "heartbeat", "timestamp": datetime.now().isoformat()}
                )
            except Exception:
                return
