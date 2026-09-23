from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from service.services.chat.application.use_cases.chat_use_cases import StreamChatResponseUseCase
from service.services.chat.domain.confirmation_offer import (
    claim_confirmation_offer,
    mark_confirmation_accepted,
    release_confirmation_claim,
)


@dataclass(slots=True)
class HandleWsChatMessageUseCase:
    job_service: Any
    chat_service: Any
    redis_client: Any = None

    async def execute(
        self, *, thread_id: str, msg: dict[str, Any], session: dict[str, Any]
    ) -> dict[str, Any]:
        text = msg.get("text")
        # Личность — ТОЛЬКО из аутентифицированной сессии. Раньше здесь было
        # `msg.get("user_id") or session.get("user_id")` — тело клиента перекрывало
        # сессию, и аутентифицированный A, прислав `user_id` жертвы B, создавал джоб и
        # списание НА B (а `user_id=all-zeros` уводил траты на общий аноним-кошелёк).
        # create_chat_job/воркер берут этот id как есть, без ре-валидации, поэтому
        # доверять клиентскому полю нельзя ни при каких условиях. HTTP-путь так и делает
        # (chat_application_service форсит user_id из check_auth) — приводим WS к тому же.
        user_id_str = session.get("user_id")
        user_id = UUID(user_id_str) if isinstance(user_id_str, str) else user_id_str
        confirmation_anchor = None
        confirm_offer_id = str(msg.get("confirm_offer_id") or "").strip()
        if confirm_offer_id:
            confirmation_anchor, duplicate = await claim_confirmation_offer(
                self.redis_client,
                confirm_offer_id,
                thread_id=thread_id,
                user_id=str(user_id or ""),
            )
            if duplicate:
                return {
                    "type": "job_created",
                    "job_id": confirmation_anchor.job_id,
                    "celery_task_id": confirmation_anchor.celery_task_id,
                    "message_id": msg.get("id"),
                    "confirmation_status": "accepted",
                    "timestamp": datetime.now().isoformat(),
                }
            text = confirmation_anchor.text
        message_id = msg.get("id")
        selected_model = (
            confirmation_anchor.selected_model if confirmation_anchor else msg.get("model")
        )
        route_override = (
            confirmation_anchor.route_override if confirmation_anchor else msg.get("route_override")
        )
        input_type = (
            confirmation_anchor.input_type if confirmation_anchor else msg.get("input_type")
        )
        web_search = bool(msg.get("web_search", False)) if not confirmation_anchor else False
        deep_research = bool(msg.get("deep_research", False)) if not confirmation_anchor else False
        file_context = msg.get("file_context", "") if not confirmation_anchor else ""
        attachments = (
            list(confirmation_anchor.attachments)
            if confirmation_anchor
            else (msg.get("attachments") or None)
        )
        # Долговременная память: по умолчанию включена (флаг отсутствует → True).
        # Фронт присылает memory_enabled=false только когда пользователь её выключил.
        memory_enabled = bool(msg.get("memory_enabled", True))
        # Per-user модель для LDR (глубокий ресёрч), может отличаться от чат-модели.
        # Пусто → overlay(админка)/config (см. deep_research._resolve_ldr_settings).
        ldr_model = msg.get("ldr_model") or None
        # Стратегия поиска LDR — тоже per-user. Имя НЕ валидируем здесь: единственная
        # точка правды — DeepResearchAgent._sanitize_strategy (LDR на незнакомое имя
        # молча откатывается на source-based, поэтому отсев там и живёт).
        ldr_strategy = msg.get("ldr_strategy") or None
        # Мульти-интент (декомпозиция запроса на под-задачи) — per-user тоггл-стратегия.
        # None (флаг не прислан) → фолбэк на глобальный admin/config-флаг в процессоре;
        # true/false — явный выбор пользователя перекрывает глобальный дефолт.
        raw_multi_intent = msg.get("multi_intent")
        multi_intent = None if raw_multi_intent is None else bool(raw_multi_intent)
        # Планирование: как и мульти-интент, ТРИ состояния. `None` — «не прислано»,
        # то есть авто по оценке сложности; булево — явная воля пользователя.
        raw_planning = msg.get("planning")
        planning = None if raw_planning is None else bool(raw_planning)
        # Личности (специализации агента) — per-user выбор НА СООБЩЕНИЕ, как режим и
        # модель. Здесь только нормализуем форму: неизвестные id и потолок разбирает
        # сайдкар, у которого есть реестр (валидировать без него значило бы гадать).
        raw_personas = msg.get("persona_ids")
        persona_ids = (
            [str(p) for p in raw_personas if str(p).strip()]
            if isinstance(raw_personas, list)
            else None
        )
        # Идентификаторы приложенных в ЭТОМ сообщении файлов. Нужны воркеру как СИГНАЛ
        # «новый файл приложен» даже когда извлечённый текст пуст (иначе он подставит
        # прежний файл треда, и агент ответит про предыдущее вложение).
        file_ids = (
            list(confirmation_anchor.file_ids)
            if confirmation_anchor
            else (msg.get("file_ids") if isinstance(msg.get("file_ids"), list) else None)
        )
        routing_usage: dict[str, Any] | None = None
        resolved_category = confirmation_anchor.resolved_category if confirmation_anchor else None
        # WebSocket is a transport for the same chat command, not a second routing
        # implementation.  The old path enqueued the raw browser payload directly, so a
        # manually selected model skipped ``/route`` entirely.  An explicit PDF request
        # then reached the run-local auto router, which offered the mode by asking the UI
        # to resend the prompt after its attachment state had already been cleared.
        # Resolve once here exactly as the REST path does; a routing outage remains
        # fail-open and keeps the user's explicit model/payload unchanged.
        routing_service = getattr(self.chat_service, "routing_service", None)
        if confirmation_anchor is None and routing_service is not None:
            try:
                route_decision = await routing_service.resolve_route(
                    text=str(text or ""),
                    selected_model=selected_model,
                    input_type=input_type,
                    web_search=web_search,
                    deep_research=deep_research,
                    route_override=route_override,
                )
            except Exception:
                route_decision = None
            if route_decision is not None:
                selected_model = route_decision.selected_model
                route_override = route_decision.route_override
                web_search = bool(route_decision.web_search)
                deep_research = bool(route_decision.deep_research)
                routing_usage = dict(route_decision.routing_usage or {}) or None
                resolved_category = route_decision.resolved_category
        # Пользователь ЯВНО открепил файл(ы) и отправил без них → воркер стирает
        # thread-память файла, а не воскрешает прежний как follow-up.
        detach_files = bool(msg.get("detach_files"))
        # 🔴 СОГЛАСИЕ НА ДОРОГОЕ — ПРИЗНАК ОДНОГО СООБЩЕНИЯ. Едет рядом с `detach_files` по
        # той же причине: это не настройка треда, а решение по этому ходу. Настройкой оно
        # означало бы, что человек согласился один раз, а платит за каждый следующий ход.
        watch_video = bool(msg.get("watch_video"))
        confirm_expensive_run = bool(confirmation_anchor) or bool(msg.get("confirm_expensive_run"))
        try:
            job_response = await self.job_service.create_chat_job(
                user_id=user_id, thread_id=thread_id, text=text
            )
            job_queue = getattr(self.job_service, "job_queue", None)
            if job_queue is None:
                raise RuntimeError("Job queue is disabled")
            task_id = job_queue.enqueue_agent_message(
                job_id=str(job_response.job_id),
                thread_id=thread_id,
                text=text,
                user_id=str(user_id) if user_id else None,
                session_data={
                    "session_id": thread_id,
                    "file_ids": file_ids,
                    "detach_files": detach_files,
                    "watch_video": watch_video,
                    "confirm_expensive_run": confirm_expensive_run,
                    "confirmed_offer_id": confirm_offer_id or None,
                    "_routing_usage": routing_usage,
                    "_resolved_category": resolved_category,
                },
                selected_model=selected_model,
                route_override=route_override,
                input_type=input_type,
                web_search=web_search,
                deep_research=deep_research,
                file_context=file_context,
                attachments=attachments,
                memory_enabled=memory_enabled,
                ldr_model=ldr_model,
                ldr_strategy=ldr_strategy,
                multi_intent=multi_intent,
                planning=planning,
                persona_ids=persona_ids,
                queue="agents",
            )
            if task_id:
                await self.job_service.update_job_celery_task_id(job_response.job_id, str(task_id))
            if confirmation_anchor is not None:
                await mark_confirmation_accepted(
                    self.redis_client,
                    confirmation_anchor,
                    job_id=str(job_response.job_id),
                    celery_task_id=str(task_id) if task_id else None,
                )
            return {
                "type": "job_created",
                "job_id": str(job_response.job_id),
                "celery_task_id": str(task_id) if task_id else None,
                "message_id": message_id,
                "confirmation_status": "accepted" if confirmation_anchor else None,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception:
            if confirmation_anchor is not None:
                await release_confirmation_claim(self.redis_client, confirmation_anchor.offer_id)
                raise
            fallback_result = await StreamChatResponseUseCase(self.chat_service).execute(
                thread_id=thread_id,
                text=text,
                user_id=str(user_id) if user_id else None,
                selected_model=selected_model,
                input_type=input_type,
                web_search=web_search,
                deep_research=deep_research,
                file_context=file_context,
                attachments=attachments,
                route_override=route_override,
                routing_metadata=None,
                confirm_expensive_run=confirm_expensive_run,
            )
            return {
                "type": "fallback",
                "message_id": message_id,
                "thread_id": thread_id,
                "selected_model": selected_model,
                "fallback_result": fallback_result,
                "timestamp": datetime.now().isoformat(),
            }
