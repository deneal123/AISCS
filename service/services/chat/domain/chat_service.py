import logging
from typing import Any, cast

from service.services.chat.application.ports.chat_ports import (
    ChatOrchestrationPort,
    ChatPersistencePort,
    ChatStreamingPort,
)
from service.services.chat.domain.attachment_meta import user_message_meta
from service.services.chat.domain.chat_contracts import (
    ChatProcessingMetadata,
    ChatReplyResult,
    ChatRequestContext,
    ChatRouteDecision,
    build_provider_unavailable_reply,
)
from service.services.chat.domain.chat_exceptions import (
    ChatErrorMapper,
    JobExecutionError,
    JobOrchestrationError,
    ModelRoutingError,
)
from service.services.chat.domain.chat_fallback_service import build_still_processing_result

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        routing_service: Any,
        orchestration_service: ChatOrchestrationPort,
        persistence_service: ChatPersistencePort,
        fallback_service: ChatStreamingPort,
    ):
        self.persistence_service = persistence_service
        self.routing_service = routing_service
        self.job_orchestrator = orchestration_service
        self.fallback_service = fallback_service

    async def create_thread(
        self,
        user_id: str | int | None,
        title: str | None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.persistence_service.create_thread(
            user_id=user_id,
            title=title,
            thread_id=thread_id,
        )

    async def post_message(self, context: ChatRequestContext) -> ChatReplyResult:
        route_decision = ChatRouteDecision(
            selected_model=context.selected_model,
            web_search=context.web_search,
            deep_research=context.deep_research,
            route_override=context.route_override,
        )
        if context.confirmed_offer_id:
            route_decision.resolved_category = context.confirmed_resolved_category
        else:
            try:
                route_decision = await self.routing_service.resolve_route(
                    text=context.text,
                    selected_model=context.selected_model,
                    input_type=context.input_type,
                    web_search=context.web_search,
                    deep_research=context.deep_research,
                    route_override=context.route_override,
                )
            except ModelRoutingError as exc:
                logger.warning("Model routing failed: %s", exc)

        # На пути джоб-оркестратора ход диалога сохраняет САМ воркер
        # (_persist_chat_turn, в его транзакции). Только fallback исполняет ответ
        # in-process и ничего не персистит — тогда сохраняем здесь.
        persisted_by_worker = True
        try:
            result = await self.job_orchestrator.execute(
                thread_id=context.thread_id,
                text=context.text,
                user_id=context.user_id,
                selected_model=route_decision.selected_model,
                input_type=context.input_type,
                web_search=route_decision.web_search,
                deep_research=route_decision.deep_research,
                file_context=context.file_context,
                attachments=context.attachments,
                file_ids=context.file_ids,
                watch_video=context.watch_video,
                confirm_expensive_run=context.confirm_expensive_run,
                confirmed_offer_id=context.confirmed_offer_id,
                route_override=route_decision.route_override,
                routing_usage=route_decision.routing_usage,
                resolved_category=route_decision.resolved_category,
            )
        except JobExecutionError as exc:
            # ⚠️ ЗАДАЧА ПОСТАВЛЕНА И ИСПОЛНЯЕТСЯ — это НЕ «очередь недоступна». Ожидание
            # результата истекло (длинный документ, долгий инструмент), но воркер живёт
            # своей жизнью: он доведёт ход до конца, сохранит его САМ и спишет деньги.
            #
            # Живой прогон: ожидание сдалось на 30-й секунде, воркер через несколько
            # секунд записал настоящий ответ на 6 403 токена — а общий fallback дописал в
            # ТОТ ЖЕ тред дубль вопроса пользователя и «сервис временно перегружен»
            # ПОВЕРХ готового ответа. То есть отказ поверх выполненной и оплаченной
            # работы, плюс мусор в истории диалога.
            logger.warning("Ожидание результата истекло, задача продолжает исполняться: %s", exc)
            result = build_still_processing_result(context.thread_id)
            result.metadata = result.metadata.merged({"error_code": ChatErrorMapper.to_code(exc)})
        except JobOrchestrationError as exc:
            if context.confirmed_offer_id:
                raise
            logger.warning("Job orchestration failed, fallback to direct agent path: %s", exc)
            result = await self.fallback_service.execute(
                thread_id=context.thread_id,
                text=context.text,
                user_id=context.user_id,
                selected_model=route_decision.selected_model,
                input_type=context.input_type,
                web_search=route_decision.web_search,
                deep_research=route_decision.deep_research,
                file_context=context.file_context,
                attachments=context.attachments,
                file_ids=context.file_ids,
                watch_video=context.watch_video,
                confirm_expensive_run=context.confirm_expensive_run,
                route_override=route_decision.route_override,
            )
            result.metadata = result.metadata.merged(
                {
                    "error_code": ChatErrorMapper.to_code(exc),
                }
            )
            persisted_by_worker = False

        if route_decision.routing_metadata:
            result.metadata = result.metadata.merged(
                {"model_routing": route_decision.routing_metadata}
            )

        # Единый owner персиста: повторный persist_messages здесь (когда ход уже
        # сохранён воркером) плодил ДУБЛИ сообщений в БД — оба слоя неидемпотентны.
        if not persisted_by_worker:
            try:
                await self.persistence_service.persist_messages(
                    context.thread_id,
                    context.text,
                    result.reply,
                    context.user_id,
                    # 🔴 Вложения реплики: без них фолбэк-путь писал сообщение
                    # пользователя пустым, и приложенный файл исчезал после F5.
                    user_message_meta(context.attachments),
                )
            except Exception:
                logger.debug("Failed to persist messages", exc_info=True)

        if not str(result.reply).strip():
            provider_error = result.metadata.data.get("provider_error")
            result.reply = build_provider_unavailable_reply(provider_error)
            provider_payload = {"provider_error": provider_error} if provider_error else {}
            result.metadata = ChatProcessingMetadata(
                data={
                    **result.metadata.data,
                    "provider_unavailable": True,
                    **provider_payload,
                }
            )
        return cast(ChatReplyResult, result)

    async def get_messages(
        self,
        thread_id: str,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        return await self.persistence_service.get_messages(
            thread_id=thread_id,
            page=page,
            per_page=per_page,
        )

    async def list_threads(
        self,
        user_id: str | int | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        return await self.persistence_service.list_threads(
            user_id=user_id,
            page=page,
            per_page=per_page,
        )

    async def delete_thread(self, thread_id: str) -> bool:
        return await self.persistence_service.delete_thread(thread_id)

    async def rename_thread(self, thread_id: str, title: str) -> bool:
        return await self.persistence_service.update_thread_title(thread_id, title)
