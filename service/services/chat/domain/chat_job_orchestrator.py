import logging

from service.services.chat.domain.chat_contracts import ChatReplyResult
from service.services.chat.domain.process_chat_message_handler import (
    ProcessChatMessageCommand,
    ProcessChatMessageFlags,
    ProcessChatMessageHandler,
    ProcessChatMessageModelSettings,
)

logger = logging.getLogger(__name__)


class ChatJobOrchestrator:
    def __init__(self, handler: ProcessChatMessageHandler) -> None:
        self.handler = handler

    async def execute(
        self,
        thread_id: str,
        text: str,
        user_id: str | int | None,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        file_context: str,
        route_override: str | None,
        attachments: list | None = None,
        file_ids: list[str] | None = None,
        watch_video: bool = False,
        confirm_expensive_run: bool = False,
        confirmed_offer_id: str | None = None,
        routing_usage: dict | None = None,
        resolved_category: str | None = None,
    ) -> ChatReplyResult:
        # usage LLM-роутера (посчитан в веб-процессе) везём в воркер внутри session_data
        # — она и так проходит web→worker как есть, без изменения сигнатур celery-задачи.
        # Воркер затарифицирует его отдельным billing_event (аудит A2).
        session_data: dict = {"session_id": thread_id}
        if routing_usage and int(routing_usage.get("total") or 0) > 0:
            session_data["_router_usage"] = dict(routing_usage)
        # Тем же каналом и по той же причине — готовый ответ авто-роутера. Без него
        # сайдкар роутит ТОТ ЖЕ текст вторым LLM-вызовом: плюс полный вызов провайдера и
        # 300-1500 мс до первого токена на КАЖДОМ сообщении, где инструмент не нужен.
        if resolved_category:
            session_data["_resolved_category"] = str(resolved_category)
        # 🔴 ТЕМ ЖЕ КАНАЛОМ, ЧТО И У WS: воркер читает файлы и согласие на видео из
        # `session_data`. Без этого HTTP-путь молча терял оба поля — ручка их принимала и
        # выбрасывала (замер: файл загружен, `file_ids` передан, агент просит прислать код).
        if file_ids:
            session_data["file_ids"] = [str(f) for f in file_ids]
        if watch_video:
            session_data["watch_video"] = True
        if confirm_expensive_run:
            session_data["confirm_expensive_run"] = True
        if confirmed_offer_id:
            session_data["confirmed_offer_id"] = str(confirmed_offer_id)
        command = ProcessChatMessageCommand(
            thread_id=thread_id,
            user_id=user_id,
            text=text,
            flags=ProcessChatMessageFlags(
                web_search=web_search,
                deep_research=deep_research,
                route_override=route_override,
                input_type=input_type,
            ),
            model_settings=ProcessChatMessageModelSettings(selected_model=selected_model),
            file_context=file_context,
            attachments=attachments,
            session_data=session_data,
        )
        return await self.handler.dispatch_and_wait(command=command, timeout_sec=30.0)
