import asyncio
import json
import logging

from celery import shared_task

from service.services.chat.domain.chat_contracts import (
    ChatProcessingMetadata,
    ChatReplyResult,
)
from service.services.chat.infrastructure.chat_worker_tasks import (
    _persist_chat_turn,
    _resolve_memory_user_id,
    _restore_pseudo_session_history,
    delete_old_chat_history,
    process_agent_message,
    process_agent_message_async,
)

logger = logging.getLogger(__name__)


def process_chat_message_core(
    thread_id: str, message_id: str, text: str, user_id: int | None = None
) -> dict:
    from service.composition import state as svc_container
    from service.infrastructure.messaging import stream_helpers as stream_helpers_module

    try:
        chat_svc = svc_container.get_current_container().services.chat_application_service
        res = asyncio.run(
            chat_svc.post_message(
                thread_id=thread_id,
                payload=type(
                    "P",
                    (),
                    {
                        "text": text,
                        "user_id": user_id,
                        "model": None,
                        "input_type": None,
                        "web_search": False,
                        "deep_research": False,
                        "file_context": "",
                        "route_override": None,
                        "file_ids": [],
                    },
                )(),
            )
        )
        res = ChatReplyResult(
            reply=res.get("reply", ""),
            thread_id=res.get("thread_id", thread_id),
            metadata=ChatProcessingMetadata(data=res.get("metadata") or {}),
        )
    except Exception:
        logger.exception("process_chat_message_core failed")
        res = ChatReplyResult(
            reply="", thread_id=thread_id, metadata=ChatProcessingMetadata(data={})
        )

    redis_client = None
    try:
        redis_client = svc_container.get_current_container().infra.redis_client
    except Exception:
        redis_client = None

    if redis_client:
        payload = {
            "type": "agent_reply",
            "id": message_id,
            "reply": res.reply,
            "metadata": res.metadata.data,
        }
        try:
            stream_helpers_module.xadd_sync(
                redis_client, f"chat:{thread_id}:stream", {"data": json.dumps(payload)}
            )
        except Exception:
            logger.exception("Failed to publish agent reply")

    return res.to_dict()


@shared_task(bind=True, name="service.infrastructure.messaging.tasks.process_chat_message")
def process_chat_message(
    self, thread_id: str, message_id: str, text: str, user_id: int | None = None
) -> dict:
    try:
        result = process_chat_message_core(thread_id, message_id, text, user_id)
        return {"status": "ok", "result": result}
    except Exception:
        logger.exception("process_chat_message failed")
        return {"status": "error"}


@shared_task(name="service.infrastructure.messaging.tasks.send_verification_email")
def send_verification_email(to: str, subject: str, html: str, text: str) -> dict:
    """Отправить письмо с кодом подтверждения через SMTP (Selectel)."""
    from service.infrastructure.mail.smtp_mailer import SmtpMailer
    from service.settings import config

    try:
        mailer = SmtpMailer(config.email)
        asyncio.run(mailer.send(to=to, subject=subject, html=html, text=text))
        return {"status": "sent"}
    except Exception as exc:
        logger.exception("send_verification_email failed for %s", to)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.send_payment_receipt_email")
def send_payment_receipt_email(
    to: str, credits: int, amount_rub: float, plan: str | None = None
) -> dict:
    """Брендовое письмо-подтверждение успешной оплаты (транзакционное, шлётся всегда).

    Рендерит шаблон здесь (у воркера есть полный config для app_url и признака, шлёт ли
    ЮKassa фискальный чек), затем отправляет через SMTP. Не путать с фискальным чеком:
    это наше подтверждение, чек присылает ЮKassa отдельно (если включён receipt_enabled).
    """
    from service.infrastructure.mail import lifecycle_templates as tpl
    from service.infrastructure.mail.smtp_mailer import SmtpMailer
    from service.settings import config

    try:
        app_url = str(config.notifications.app_url).rstrip("/")
        subject, html, text = tpl.payment_succeeded(
            credits=int(credits or 0),
            amount_rub=float(amount_rub or 0),
            plan=plan,
            app_url=app_url,
            receipt_by_email=bool(getattr(config.payments, "receipt_enabled", False)),
        )
        mailer = SmtpMailer(config.email)
        asyncio.run(mailer.send(to=to, subject=subject, html=html, text=text))
        return {"status": "sent"}
    except Exception as exc:
        logger.exception("send_payment_receipt_email failed for %s", to)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.cleanup_old_streams")
def cleanup_old_streams():
    from service.infrastructure.cache.redis_manager import RedisManager
    from service.infrastructure.messaging import stream_helpers
    from service.settings import Config

    try:
        config = Config()
        if not config.redis or not config.redis.enabled:
            return {"status": "skipped", "reason": "redis_disabled"}
        redis_client = RedisManager(config.redis).get_client()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            trimmed = loop.run_until_complete(
                stream_helpers.cleanup_old_streams(
                    redis_client, pattern="chat:*:stream", maxlen=1000
                )
            )
            return {"status": "success", "trimmed": trimmed}
        finally:
            loop.close()
    except Exception as exc:
        logger.exception("Failed to cleanup old streams: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.recheck_blocked_providers")
def recheck_blocked_providers():
    """Точечная самопроверка ТОЛЬКО заблокированных провайдеров (не пуллинг всех).

    Заблокированный health-проверкой провайдер, снова прошедший живую пробу, автоматически
    разблокируется. Здоровые провайдеры не трогаем — это НЕ постоянный пуллинг.
    """
    from service.infrastructure import provider_policy_store as provider_policy
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.admin.application.admin_service import AdminService
    from service.services.admin.persistence.app_settings_repository import AppSettingsRepository
    from service.settings import Config

    try:
        config = Config()
        connector = PgConnector(config.pg, force_new=True)
        app_settings_repo = AppSettingsRepository(connector)
        provider_policy.bind(app_settings_repo)  # для persistent clear_blocked
        service = AdminService(None, app_settings_repo)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(provider_policy.prime())  # засеять из БД
            result = loop.run_until_complete(service.recheck_blocked_providers())
            return {"status": "success", **result}
        finally:
            if close_connector := getattr(connector, "close", None):
                loop.run_until_complete(close_connector())
            loop.close()
    except Exception as exc:
        logger.exception("Failed to recheck blocked providers: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.reconcile_pending_payments")
def reconcile_pending_payments():
    """Периодическая сверка платежей: если вебхук ЮKassa не дошёл, до-начисляем.

    Для mock-провайдера (dev) — no-op (нет authoritative-переполучения). В проде
    (yookassa) перезапрашивает статус зависших pending по API и начисляет
    идемпотентно. Так оплата не теряется, даже если /webhook был недоступен.
    """
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.billing.application.billing_service import BillingService
    from service.services.billing.infrastructure.payments.factory import build_payment_provider
    from service.services.billing.persistence.billing_repository import BillingRepository
    from service.settings import Config

    try:
        config = Config()
        connector = PgConnector(config.pg, force_new=True)
        service = BillingService(
            BillingRepository(connector),
            config.billing,
            payment_provider=build_payment_provider(config.payments),
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(service.reconcile_pending_payments())
            return {"status": "success", **result}
        finally:
            if close_connector := getattr(connector, "close", None):
                loop.run_until_complete(close_connector())
            loop.close()
    except Exception as exc:
        logger.exception("Failed to reconcile pending payments: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.cleanup_expired_reservations")
def cleanup_expired_reservations():
    """Release abandoned reservations without ever mutating committed records."""
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.billing.application.cost_guard import (
        cleanup_expired_reservations as cleanup_reservations,
    )
    from service.services.billing.persistence.billing_repository import BillingRepository
    from service.settings import Config

    async def run_cleanup() -> dict:
        # PgConnector must be created in the loop that uses its asyncpg pool.
        # Celery's synchronous task body otherwise binds it to a stale/default
        # loop before asyncio.run creates the task loop.
        config = Config()
        repo = BillingRepository(PgConnector(config.pg))
        return await cleanup_reservations(repo)

    try:
        return {"status": "success", **asyncio.run(run_cleanup())}
    except Exception as exc:
        logger.exception("Failed to cleanup expired reservations: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.refresh_provider_pricing")
def refresh_provider_pricing():
    """Refresh RouterAI/OpenRouter tariffs without ever replacing manual prices."""
    from service.infrastructure.database.postgresql import PgConnector
    from service.services.billing.application.provider_pricing_sync import (
        ProviderPricingSyncService,
    )
    from service.services.billing.persistence.billing_repository import BillingRepository
    from service.settings import Config

    async def run_refresh() -> dict:
        # Keep connector construction in asyncio.run's loop; a price refresh is
        # scheduled repeatedly in the same worker process.
        config = Config()
        service = ProviderPricingSyncService(BillingRepository(PgConnector(config.pg)))
        return await service.refresh()

    try:
        return {"status": "success", **asyncio.run(run_refresh())}
    except Exception as exc:
        logger.exception("Failed to refresh provider pricing: %s", exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.maintain_workflow_catalog")
def maintain_workflow_catalog():
    """Hourly retention/lifecycle/outbox maintenance for the autonomous workflow catalog."""

    async def run_maintenance() -> dict:
        from service.infrastructure.agents_client.workflow_catalog import deliver
        from service.infrastructure.database.postgresql import PgConnector
        from service.services.admin.application.runtime_settings import runtime_settings
        from service.services.admin.persistence.app_settings_repository import (
            AppSettingsRepository,
        )
        from service.services.chat.persistence import workflow_catalog
        from service.services.chat.persistence.workflow_catalog_metrics import catalog_metrics
        from service.settings import Config

        config = Config()
        connector = PgConnector(config.pg)
        runtime_settings.ensure_bound(lambda: AppSettingsRepository(connector))
        await runtime_settings.refresh(force=True)
        lease_sec = int(
            runtime_settings.get_agents(
                "workflow_catalog_outbox_lease_sec",
                config.agents.workflow_catalog_outbox_lease_sec,
            )
        )
        retry_max_sec = int(
            runtime_settings.get_agents(
                "workflow_catalog_outbox_retry_max_sec",
                config.agents.workflow_catalog_outbox_retry_max_sec,
            )
        )
        async with connector.get_session_context() as session:
            result = await workflow_catalog.maintain(session)
            rows = await workflow_catalog.claim_pending_outbox(session, lease_sec=lease_sec)
            await session.commit()
        delivered = 0
        deferred = 0
        for row in rows:
            outcome = await deliver(config, row)
            async with connector.get_session_context() as session:
                await workflow_catalog.mark_outbox(
                    session,
                    outbox_id=row["id"],
                    lease_token=row["lease_token"],
                    delivered=outcome.delivered,
                    error_class=outcome.error_class,
                    retry_max_sec=retry_max_sec,
                )
                await session.commit()
            catalog_metrics.delivery(outcome.delivered, outcome.error_class)
            delivered += int(outcome.delivered)
            deferred += int(not outcome.delivered)
        async with connector.get_session_context() as session:
            snapshot = await workflow_catalog.outbox_snapshot(session)
        catalog_metrics.snapshot(**snapshot)
        catalog_metrics.maintenance("success")
        return {**result, **snapshot, "delivered": delivered, "deferred": deferred}

    try:
        return {"status": "success", **asyncio.run(run_maintenance())}
    except Exception as exc:
        logger.exception("Failed to maintain workflow catalog")
        try:
            from service.services.chat.persistence.workflow_catalog_metrics import catalog_metrics

            catalog_metrics.maintenance("error")
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}


@shared_task(name="service.infrastructure.messaging.tasks.deliver_document_publications")
def deliver_document_publications():
    """Lease and deliver audited PDFs/source bundles without blocking chat completion."""

    async def run_delivery() -> dict:
        from service.infrastructure.database.postgresql import PgConnector
        from service.services.chat.application.document_publication_service import deliver_one
        from service.services.chat.infrastructure.chat_worker.factory import (
            ChatWorkerDependencyFactory,
            build_file_service,
        )
        from service.services.chat.persistence import document_publications
        from service.settings import Config

        config = Config()
        factory = ChatWorkerDependencyFactory()
        connector = PgConnector(config.pg)
        try:
            redis = factory.create_redis_client(config)
            async with connector.get_session_context() as session:
                rows = await document_publications.claim(session, limit=8, lease_sec=120)
                await session.commit()
            counts = {"delivered": 0, "deferred": 0, "terminal": 0}
            if not rows:
                return {"claimed": 0, **counts}
            try:
                file_service = build_file_service(config, connector)
            except Exception:
                for row in rows:
                    async with connector.get_session_context() as session:
                        await document_publications.defer(
                            session,
                            job_id=row["id"],
                            lease_token=row["lease_token"],
                            failure_code="unavailable",
                        )
                        await session.commit()
                return {"claimed": len(rows), **counts, "deferred": len(rows)}
            for row in rows:
                async with connector.get_session_context() as session:
                    outcome = await deliver_one(
                        config=config,
                        pg_connector=connector,
                        redis=redis,
                        file_service=file_service,
                        session=session,
                        row=row,
                    )
                    await session.commit()
                counts[outcome] = counts.get(outcome, 0) + 1
            return {"claimed": len(rows), **counts}
        finally:
            await connector.close()

    try:
        return {"status": "success", **asyncio.run(run_delivery())}
    except Exception:
        logger.warning(
            "document publication maintenance failed",
            extra={"component": "document_publication", "failure_code": "unavailable"},
        )
        return {"status": "error", "error": "unavailable"}


__all__ = [
    "process_chat_message_core",
    "process_chat_message",
    "reconcile_pending_payments",
    "cleanup_expired_reservations",
    "refresh_provider_pricing",
    "maintain_workflow_catalog",
    "deliver_document_publications",
    "process_agent_message_async",
    "process_agent_message",
    "delete_old_chat_history",
    "cleanup_old_streams",
    "recheck_blocked_providers",
    "send_verification_email",
    "send_payment_receipt_email",
    "_resolve_memory_user_id",
    "_restore_pseudo_session_history",
    "_persist_chat_turn",
]
