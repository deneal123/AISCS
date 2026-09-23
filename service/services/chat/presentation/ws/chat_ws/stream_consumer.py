import asyncio
import json
import logging
from datetime import datetime

from starlette.websockets import WebSocketDisconnect

from service.infrastructure.messaging import stream_helpers
from service.services.chat.domain.mode_offer import sanitize_mode_offer_metadata
from service.services.chat.presentation.ws.chat_ws.metrics import ChatWsMetrics

logger = logging.getLogger(__name__)

# Устойчивый сбой (Redis недоступен / мёртвый сокет): после стольких подряд ошибок
# консьюмер выходит, а не крутится вечно, спамя логами и держа корутину.
_MAX_CONSECUTIVE_STREAM_ERRORS = 8


class ChatStreamConsumer:
    def __init__(self, redis_client, settings, metrics: ChatWsMetrics) -> None:
        self._redis_client = redis_client
        self._settings = settings
        self._metrics = metrics

    async def ensure_group(self, stream_key: str, group: str) -> None:
        await stream_helpers.ensure_group(self._redis_client, stream_key, group, mkstream=True)

    async def handle_replay(self, websocket, stream_key: str, last_id: str) -> None:
        replay_count = min(self._settings.max_replay, 100)
        entries = await stream_helpers.xrange(
            self._redis_client, stream_key, last_id, "+", count=replay_count
        )
        for entry_id, fields in entries:
            payload = self.parse_payload(fields)
            await websocket.send_json({"type": "replay", "id": entry_id, "data": payload})
            self._metrics.inc("replay_sent_total")

    async def process_claimed_entries(
        self, websocket, stream_key: str, group: str, claimed: list
    ) -> None:
        for entry_id, fields in claimed:
            payload = self.parse_payload(fields)
            try:
                await websocket.send_json({"type": "claimed", "id": entry_id, "data": payload})
                self._metrics.inc("claimed_sent_total")
            except Exception:
                self._metrics.inc("claimed_left_unacked_total")
                logger.debug("Failed sending claimed entry %s", entry_id, exc_info=True)
                continue

            try:
                await stream_helpers.xack(self._redis_client, stream_key, group, entry_id)
            except Exception:
                self._metrics.inc("xack_errors_total")
                logger.debug("Failed xack for claimed entry %s", entry_id, exc_info=True)

    async def handle_pending_messages(
        self, websocket, stream_key: str, group: str, consumer: str
    ) -> None:
        pending = await stream_helpers.xpending(self._redis_client, stream_key, group)
        pending_count = pending.get("count", 0) if pending else 0
        if pending_count <= 0:
            return

        claim_limit = min(pending_count, self._settings.max_claim)
        claimed = await stream_helpers.xauto_claim(
            self._redis_client,
            stream_key,
            group,
            consumer,
            min_idle_ms=self._settings.pel_min_idle_ms,
            count=claim_limit,
        )
        await self.process_claimed_entries(websocket, stream_key, group, claimed)

    async def resolve_cursor(self, stream_key: str, start_from_latest: bool) -> str:
        """С какого места читать. Вызывать ДО приёма сообщений от клиента.

        🔴 «$» РАЗРЕШАЕТСЯ В МОМЕНТ ЧТЕНИЯ, а не подписки. Курсор ставился первым
        блокирующим `XREAD` — то есть уже после того, как сокет начал принимать сообщения
        и воркер мог начать публиковать. Живой прогон: события `auto_decision` и
        `mode_offer` уходили в этот зазор и терялись НАВСЕГДА; снаружи это выглядело как
        «трейс без первых шагов», а после переезда карточки режима в трейс — как
        «предложение не пришло вовсе». Разрешаем хвост ЗАРАНЕЕ и явно.
        """
        if not start_from_latest:
            return "0"
        return await stream_helpers.last_entry_id(self._redis_client, stream_key)

    async def consume_events(
        self,
        websocket,
        stream_key: str,
        group: str,
        consumer: str,
        start_from_latest: bool = False,
        cursor: str | None = None,
    ) -> None:
        last_id = cursor or await self.resolve_cursor(stream_key, start_from_latest)
        consecutive_errors = 0
        while True:
            try:
                messages = await stream_helpers.xread(
                    self._redis_client,
                    streams={stream_key: last_id},
                    count=10,
                    block=1000,
                )
                for _, message_list in messages:
                    for message_id, fields in message_list:
                        event_data = self.parse_payload(fields)
                        self._record_tool_metrics(event_data)
                        payload = self.build_event_payload(event_data)
                        await websocket.send_json(payload)
                        self._metrics.inc("events_sent_total")
                        last_id = message_id
                consecutive_errors = 0  # успешная итерация — сбрасываем счётчик ошибок
            except WebSocketDisconnect:
                # Клиент отключился — консьюмер без живого сокета бессмыслен, выходим
                # (иначе send_json падал бы в цикле, крутя бесконечный лог ошибок).
                logger.debug("Chat stream consumer stopped: websocket disconnected")
                return
            except Exception:
                consecutive_errors += 1
                logger.exception(
                    "Error in chat stream consumer (consecutive=%d)", consecutive_errors
                )
                if consecutive_errors >= _MAX_CONSECUTIVE_STREAM_ERRORS:
                    logger.error(
                        "Chat stream consumer giving up after %d consecutive errors",
                        consecutive_errors,
                    )
                    self._metrics.inc("stream_consumer_gave_up_total")
                    return
                # Backoff с капом — не спамим и не жжём CPU при недоступности Redis.
                await asyncio.sleep(min(0.5 * consecutive_errors, 5.0))
                continue
            await asyncio.sleep(0.1)

    def _record_tool_metrics(self, event_data: dict) -> None:
        """Extract bounded tool lifecycle signals from the additive agent metadata."""
        metadata = event_data.get("metadata") if isinstance(event_data, dict) else None
        if not isinstance(metadata, dict):
            return
        event_type = event_data.get("type")
        if event_type == "agent_reply":
            integrity = metadata.get("usage_integrity") or {}
            if isinstance(integrity, dict):
                for reason in integrity.get("reason_codes") or []:
                    self._metrics.usage_integrity(reason=str(reason))
            return
        if event_type == "error" and event_data.get("error_code") == "no_compatible_model":
            self._metrics.provider_qualification(
                provider=str(metadata.get("provider") or "unknown"),
                status="no_compatible_model",
            )
            return
        if event_type != "status_update":
            return
        kind = metadata.get("kind")
        if kind == "tool_progress":
            progress = metadata.get("tool_progress") or {}
            if isinstance(progress, dict):
                reason = str(progress.get("reason") or "")
                dedup_reason = str(progress.get("dedup_reason") or "")
                if not reason and dedup_reason in {"inflight", "completed", "observed"}:
                    reason = f"dedup_{dedup_reason}"
                self._metrics.tool_event(
                    kind="progress",
                    status=str(progress.get("status") or ""),
                    reason=reason,
                    duration_ms=progress.get("duration_ms"),
                )
        elif kind == "tool_availability":
            availability = metadata.get("tool_availability") or {}
            if isinstance(availability, dict):
                for omission in availability.get("omissions") or []:
                    if isinstance(omission, dict):
                        self._metrics.tool_event(
                            kind="omission", reason=str(omission.get("reason") or "")
                        )
                for _ in availability.get("offered") or []:
                    self._metrics.tool_event(kind="offered")
        elif kind == "tool_summary":
            summary = metadata.get("tool_summary") or {}
            self._metrics.tool_event(
                kind="summary",
                status=(
                    "round_cap"
                    if isinstance(summary, dict) and summary.get("round_cap_reached")
                    else ""
                ),
            )
        elif kind == "tool_disclosure":
            disclosure = metadata.get("tool_disclosure") or {}
            if isinstance(disclosure, dict):
                self._metrics.tool_event(
                    kind="disclosure",
                    status=str(disclosure.get("mode") or ""),
                    reason=str(disclosure.get("fallback_reason") or ""),
                )
                self._metrics.disclosure_savings(
                    mode=str(disclosure.get("mode") or "unknown"),
                    tokens=self._safe_int(disclosure.get("schema_tokens_saved")),
                )
        elif kind == "integration_health":
            health = metadata.get("integration_health") or {}
            if isinstance(health, dict):
                mode = str(health.get("mode") or "unknown")
                reasons = health.get("reasons") or {}
                if isinstance(reasons, dict) and reasons:
                    for reason, value in reasons.items():
                        self._metrics.integration_event(
                            mode=mode, reason=str(reason), value=self._safe_int(value)
                        )
                else:
                    self._metrics.integration_event(mode=mode)
        elif kind == "workflow_execution":
            execution = metadata.get("workflow_execution") or {}
            if isinstance(execution, dict):
                self._metrics.workflow_execution(
                    status=str(execution.get("status") or "unknown"),
                    cost_class=str(execution.get("cost_class") or "unknown"),
                )
        elif kind == "run_integrity":
            integrity = metadata.get("run_integrity") or {}
            if isinstance(integrity, dict):
                for reason in integrity.get("reasons") or []:
                    self._metrics.run_integrity(reason=str(reason))
                    self._metrics.stream_protocol(stage="ndjson", reason=str(reason))
        elif kind == "tool_intent":
            intent = metadata.get("tool_intent") or {}
            if isinstance(intent, dict):
                self._metrics.grounding(
                    state=str(intent.get("state") or "unknown"),
                    reason=str(intent.get("reason") or ""),
                )

    @staticmethod
    def _safe_int(value) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def parse_payload(fields: dict) -> dict:
        try:
            data = fields.get("data") if isinstance(fields, dict) else fields
            return json.loads(data) if isinstance(data, str) else (data or {})
        except Exception:
            return {}

    @staticmethod
    def build_event_payload(event_data: dict) -> dict:
        event_type = event_data.get("type") or event_data.get("event")
        timestamp = event_data.get("timestamp") or datetime.now().isoformat()
        raw_metadata = event_data.get("metadata")
        metadata = (
            sanitize_mode_offer_metadata(raw_metadata)
            if isinstance(raw_metadata, dict)
            else raw_metadata
        )
        if event_type == "agent_reply":
            return {
                "type": "agent_reply",
                "job_id": event_data.get("job_id"),
                "reply": event_data.get("reply"),
                "file_url": event_data.get("file_url"),
                "error": event_data.get("error"),
                "metadata": metadata,
                "timestamp": timestamp,
            }
        if event_type == "stream_chunk":
            return {
                "type": "stream_chunk",
                "data": event_data.get("data"),
                "job_id": event_data.get("job_id"),
                "metadata": metadata,
                "seq": event_data.get("seq"),
                "timestamp": timestamp,
            }
        payload = {
            "type": event_type,
            "job_id": event_data.get("job_id"),
            # Never use the whole internal envelope as a display fallback: it
            # can contain legacy metadata that was intentionally redacted above.
            "data": event_data.get("data"),
            "message": event_data.get("message"),
            "agent_name": event_data.get("agent_name"),
            "tool_name": event_data.get("tool_name"),
            "error": event_data.get("error"),
            "metadata": metadata,
            "seq": event_data.get("seq"),
            "timestamp": timestamp,
        }
        return {k: v for k, v in payload.items() if v is not None}
