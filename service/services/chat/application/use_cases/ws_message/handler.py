"""WS job lifecycle: authenticated identity, offer claim and dispatch ACK boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from service.services.chat.application.use_cases.chat_use_cases import StreamChatResponseUseCase
from service.services.chat.application.use_cases.ws_message.admission import admit_ws_message
from service.services.chat.application.use_cases.ws_message.options import WsMessageOptions
from service.services.chat.domain.confirmation.offer import (
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
        # Only authenticated session identity may own the job and its charges.
        # Browser user_id/session_data must never override it, including all-zeros IDs.
        user_id_str = session.get("user_id")
        user_id = UUID(user_id_str) if isinstance(user_id_str, str) else user_id_str
        confirmation_anchor = None
        confirm_offer_id = str(msg.get("confirm_offer_id") or "").strip()
        confirmation_decision = str(msg.get("confirmation_decision") or "accept")
        if confirm_offer_id:
            confirmation_anchor, duplicate = await claim_confirmation_offer(
                self.redis_client,
                confirm_offer_id,
                thread_id=thread_id,
                user_id=str(user_id or ""),
                decision=confirmation_decision,
            )
            if duplicate:
                return {
                    "type": "job_created",
                    "job_id": confirmation_anchor.job_id,
                    "celery_task_id": confirmation_anchor.celery_task_id,
                    "message_id": msg.get("id"),
                    "confirmation_status": confirmation_anchor.status,
                    "confirmation_offer_id": confirm_offer_id,
                    "timestamp": datetime.now().isoformat(),
                }
        options = WsMessageOptions.from_message(
            msg,
            anchor=confirmation_anchor,
            offer_id=confirm_offer_id,
            decision=confirmation_decision,
        )
        admission = await admit_ws_message(
            redis_client=self.redis_client,
            routing_service=getattr(self.chat_service, "routing_service", None),
            thread_id=thread_id,
            user_id=str(user_id or ""),
            text=options.text,
            msg=msg,
            confirmation_anchor=confirmation_anchor,
            selection=options.route,
        )
        options = options.after_admission(
            admission, anchor=confirmation_anchor, decision=confirmation_decision
        )
        dispatch_attempted = False
        try:
            job_response = await self.job_service.create_chat_job(
                user_id=user_id, thread_id=thread_id, text=options.text
            )
            job_queue = getattr(self.job_service, "job_queue", None)
            if job_queue is None:
                raise RuntimeError("Job queue is disabled")
            # An exception after invoking transport cannot prove broker rejection.
            # Keep the claim across an unknown ACK: never dispatch a paid continuation twice.
            dispatch_attempted = True
            task_id = job_queue.enqueue_agent_message(
                job_id=str(job_response.job_id),
                thread_id=thread_id,
                text=options.text,
                user_id=str(user_id) if user_id else None,
                **options.worker_options(thread_id, admission),
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
                **(
                    {"document_project": admission.document_context["project_id"]}
                    if admission.document_context
                    else {}
                ),
                "job_id": str(job_response.job_id),
                "celery_task_id": str(task_id) if task_id else None,
                "message_id": options.message_id,
                **(
                    {
                        "confirmation_status": "declined"
                        if confirmation_decision == "decline"
                        else "accepted",
                        "confirmation_offer_id": confirm_offer_id,
                    }
                    if confirmation_anchor
                    else {}
                ),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception:
            if confirmation_anchor is not None:
                if not dispatch_attempted:
                    await release_confirmation_claim(
                        self.redis_client, confirmation_anchor.offer_id
                    )
                raise
            if admission.ide_context:
                # Never replay an unknown enqueue or use the legacy Chat binding.
                raise
            fallback_result = await StreamChatResponseUseCase(self.chat_service).execute(
                document_context=admission.document_context,
                thread_id=thread_id,
                text=options.text,
                user_id=str(user_id) if user_id else None,
                **options.fallback_options(),
            )
            return {
                "type": "fallback",
                "message_id": options.message_id,
                "thread_id": thread_id,
                "selected_model": options.route.selected_model,
                "fallback_result": fallback_result,
                "timestamp": datetime.now().isoformat(),
            }
