"""Celery application configuration.

This module configures the Celery app for background task processing.
It supports both RabbitMQ as the broker and Redis as the result backend.
"""

import logging
import os
import re

from celery import Celery  # type: ignore[import]

logger = logging.getLogger(__name__)

# Celery configuration from environment variables
if (
    os.getenv("CELERY__BROKER_URL")
    and os.getenv("CELERY_BROKER_URL")
    and os.environ["CELERY__BROKER_URL"] != os.environ["CELERY_BROKER_URL"]
):
    raise RuntimeError("Conflicting Celery broker configuration")
CELERY_BROKER_URL = os.getenv("CELERY__BROKER_URL") or os.getenv(
    "CELERY_BROKER_URL", "amqp://guest:guest@rabbitmq:5672//"
)
CELERY_RESULT_BACKEND = os.getenv("CELERY__RESULT_BACKEND", "redis://redis:6379/1")


def _redact_url_credentials(url: str) -> str:
    return re.sub(r"//[^/@]*@", "//***:***@", url)


# Create Celery app
celery_app = Celery(
    "eater",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "service.infrastructure.messaging.tasks",
        "service.services.notifications.tasks",
        "service.services.files.infrastructure.maintenance",
        "service.services.chat.infrastructure.ide_checkpoint_maintenance",
        "service.services.simulations.tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task execution
    task_acks_late=True,  # Acknowledge after task completion
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    # Task time limits
    task_soft_time_limit=3600,  # 1 hour soft limit
    task_time_limit=3900,  # 1 hour 5 min hard limit
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time per worker
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory cleanup)
    # Result backend settings
    result_expires=86400,  # Results expire after 24 hours
    result_extended=True,  # Store additional task metadata
    # Retry settings
    task_default_retry_delay=60,  # 1 minute default retry delay
    task_max_retries=3,  # Maximum 3 retries
    # Queue routing with priorities
    task_default_queue="agents",  # Default queue for agent tasks
    task_routes={
        "service.services.simulations.tasks.execute_run": {"queue": "simulation"},
        "service.services.simulations.tasks.recover_runs": {"queue": "maintenance"},
        "service.infrastructure.messaging.tasks.dispatch_human_question_children": {
            "queue": "maintenance",
            "priority": 3,
        },
        "service.services.files.infrastructure.maintenance.cleanup_pending_uploads": {
            "queue": "maintenance",
            "priority": 1,
        },
        "service.infrastructure.messaging.tasks.process_agent_message": {
            "queue": "agents",
            "priority": 5,  # High priority for agent messages
        },
        "service.infrastructure.messaging.tasks.cleanup_old_streams": {
            "queue": "maintenance",
            "priority": 1,  # Low priority for cleanup tasks
        },
        "service.infrastructure.messaging.tasks.cleanup_expired_reservations": {
            "queue": "maintenance",
            "priority": 2,
        },
        "service.infrastructure.messaging.tasks.refresh_provider_pricing": {
            "queue": "maintenance",
            "priority": 2,
        },
        "service.infrastructure.messaging.tasks.maintain_workflow_catalog": {
            "queue": "maintenance",
            "priority": 2,
        },
        "service.infrastructure.messaging.tasks.deliver_document_publications": {
            "queue": "maintenance",
            "priority": 3,
        },
        "service.services.chat.infrastructure.ide_checkpoint_maintenance.cleanup": {
            "queue": "maintenance",
            "priority": 1,
        },
        "service.infrastructure.messaging.tasks.delete_old_chat_history": {
            "queue": "maintenance",
            "priority": 1,  # Low priority for cleanup tasks
        },
        "service.infrastructure.messaging.tasks.send_verification_email": {
            "queue": "maintenance",
            "priority": 3,  # Higher than cleanup: users wait on the code
        },
    },
    # Define queues with priority support
    task_queues={
        "simulation": {"exchange": "simulation", "routing_key": "simulation"},
        "agents": {
            "exchange": "agents",
            "routing_key": "agents",
            "queue_arguments": {"x-max-priority": 10},  # Support priorities 0-10
        },
        "maintenance": {
            "exchange": "maintenance",
            "routing_key": "maintenance",
            "queue_arguments": {"x-max-priority": 5},  # Lower priority range for maintenance
        },
    },
)

# Beat schedule for periodic tasks (if needed)
celery_app.conf.beat_schedule = {
    "cleanup-ide-checkpoints": {
        "task": "service.services.chat.infrastructure.ide_checkpoint_maintenance.cleanup",
        "schedule": 300.0,
    },
    "dispatch-human-question-children": {
        "task": "service.infrastructure.messaging.tasks.dispatch_human_question_children",
        "schedule": 60.0,
    },
    "cleanup-pending-uploads": {
        "task": "service.services.files.infrastructure.maintenance.cleanup_pending_uploads",
        "schedule": 3600.0,
    },
    # Clean up old chat messages once per day by default (configurable via env)
    "cleanup-old-chat-history": {
        "task": "service.infrastructure.messaging.tasks.delete_old_chat_history",
        "schedule": float(os.getenv("CHAT_RETENTION_SCHEDULE_SECONDS", str(24 * 3600))),
    },
    # Clean up old Redis Streams every hour
    "cleanup-old-streams": {
        "task": "service.infrastructure.messaging.tasks.cleanup_old_streams",
        "schedule": 3600.0,  # Every hour
    },
    # Reconcile payments whose webhook may have been lost (no-op for mock provider)
    "reconcile-pending-payments": {
        "task": "service.infrastructure.messaging.tasks.reconcile_pending_payments",
        "schedule": float(os.getenv("PAYMENT_RECONCILE_SCHEDULE_SECONDS", str(15 * 60))),
    },
    "cleanup-expired-reservations": {
        "task": "service.infrastructure.messaging.tasks.cleanup_expired_reservations",
        "schedule": float(os.getenv("RESERVATION_CLEANUP_SCHEDULE_SECONDS", "60")),
    },
    "refresh-provider-pricing": {
        "task": "service.infrastructure.messaging.tasks.refresh_provider_pricing",
        "schedule": float(os.getenv("PRICING_SYNC_SCHEDULE_SECONDS", str(24 * 3600))),
    },
    "maintain-workflow-catalog": {
        "task": "service.infrastructure.messaging.tasks.maintain_workflow_catalog",
        "schedule": 3600.0,
    },
    "deliver-document-publications": {
        "task": "service.infrastructure.messaging.tasks.deliver_document_publications",
        "schedule": 60.0,
    },
    # Точечная самопроверка ТОЛЬКО заблокированных провайдеров: снова живой → авто-разблок.
    # Не пуллинг всех — трогает лишь заблокированные (по умолчанию раз в 5 минут).
    "recheck-blocked-providers": {
        "task": "service.infrastructure.messaging.tasks.recheck_blocked_providers",
        "schedule": float(os.getenv("PROVIDER_RECHECK_SCHEDULE_SECONDS", str(5 * 60))),
    },
    # Жизненные уведомления (подписка/кредиты/платежи/реактивация) — раз в сутки.
    # Идемпотентность держится на dedup_key, поэтому лишний прогон писем не задваивает.
    "lifecycle-notifications": {
        "task": "service.services.notifications.tasks.send_lifecycle_notifications",
        "schedule": float(os.getenv("NOTIFICATIONS_SCHEDULE_SECONDS", str(24 * 3600))),
    },
}

if os.getenv("SERVICE__APPLICATION_PROFILE") == "simulation":
    # Preserve shared storage/stream housekeeping. Chat, billing, provider and
    # document schedules remain defined above for the GPTHub profile.
    shared_maintenance = {
        name: entry
        for name, entry in celery_app.conf.beat_schedule.items()
        if entry["task"]
        in {
            "service.services.files.infrastructure.maintenance.cleanup_pending_uploads",
            "service.infrastructure.messaging.tasks.cleanup_old_streams",
        }
    }
    celery_app.conf.beat_schedule = {
        **shared_maintenance,
        "recover-simulation-runs": {
            "task": "service.services.simulations.tasks.recover_runs",
            "schedule": 10.0,
            "options": {"queue": "maintenance"},
        },
    }

logger.info("Celery app configured with broker: %s", _redact_url_credentials(CELERY_BROKER_URL))
