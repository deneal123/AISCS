from __future__ import annotations

from service.composition.models import InfraContainer, RepositoriesContainer, ServicesContainer
from service.infrastructure.mail.dispatcher import VerificationCodeDispatcher
from service.infrastructure.mail.smtp_mailer import SmtpMailer
from service.services.admin.application.admin_service import AdminService
from service.services.admin.application.runtime_settings import (
    OverlayBillingConfig,
    runtime_settings,
)
from service.services.admin.persistence.admin_repository import AdminRepository
from service.services.admin.persistence.app_settings_repository import AppSettingsRepository
from service.services.analytics.application.analytics_service import AnalyticsService
from service.services.analytics.persistence.analytics_repository import AnalyticsVitalsRepository
from service.services.billing.application.billing_service import BillingService
from service.services.billing.infrastructure.payments.factory import build_payment_provider
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.composition import build_chat_components
from service.services.chat.domain.process_chat_message_handler import ProcessChatMessageHandler
from service.services.chat.persistence.chat_repository import ChatRepository
from service.services.files.application.file_saver_service import FileSaverService
from service.services.jobs.application.job_processor import NewJobProcessor
from service.services.jobs.application.job_service import JobService
from service.services.profile.application.auth_service import AuthService
from service.services.profile.application.profile_service import ProfileService
from service.settings import Config


def build_services(
    repos: RepositoriesContainer,
    infra: InfraContainer,
    config: Config,
) -> ServicesContainer:
    profile_service = ProfileService(
        config.profile,
        repos.profile_repository,
        cache=infra.redis_cache,
        cache_ttl_seconds=(
            config.redis.profile_cache_ttl_seconds if infra.redis_cache and config.redis else None
        ),
    )
    # Email-верификация: код хранится в Redis (redis_cache), отправляется через
    # Celery/SMTP (VerificationCodeDispatcher). Секреты SMTP — только из env.
    verification_code_sender = VerificationCodeDispatcher(
        SmtpMailer(config.email),
        enabled=config.email.enabled,
        dev_mode=config.auth.dev_mode,
        ttl_seconds=config.email.code_ttl_seconds,
    )
    auth_service = AuthService(
        config.auth,
        repos.auth_repository,
        profile_service,
        email_config=config.email,
        cache=infra.redis_cache,
        code_sender=verification_code_sender,
    )
    job_service = JobService(
        config.job,
        repos.job_repository,
        job_queue=infra.job_queue_port,
    )

    file_saver_service = FileSaverService(
        repository=repos.file_repository,
        folder_name="uploads",
        file_storage=infra.storage,
        message_bus=infra.message_bus_port,
    )

    analytics_service = AnalyticsService(AnalyticsVitalsRepository(redis_client=infra.redis_client))

    process_chat_message_handler = ProcessChatMessageHandler(
        job_service=job_service,
        job_queue=infra.job_queue_port,
        redis_client=infra.redis_client,
    )

    new_job_processor = NewJobProcessor(
        config.job,
        repos.job_repository,
    )

    chat_components = build_chat_components(
        repository=ChatRepository(infra.pg_connector),
        job_handler=process_chat_message_handler,
        file_service=file_saver_service,
        redis_client=infra.redis_client,
    )

    # Runtime-overlay настроек: админ-правки экономики применяются без передеплоя.
    app_settings_repo = AppSettingsRepository(infra.pg_connector)
    runtime_settings.bind(app_settings_repo)
    # Persistent health-блок провайдеров (тот же репозиторий app_settings для durability).
    from service.infrastructure import provider_policy_store as provider_policy

    provider_policy.bind(app_settings_repo)
    billing_service = BillingService(
        BillingRepository(infra.pg_connector),
        OverlayBillingConfig(config.billing, runtime_settings),
        payment_provider=build_payment_provider(config.payments),
    )
    admin_service = AdminService(
        AdminRepository(infra.pg_connector), app_settings_repo, profile_cache=infra.redis_cache
    )

    return ServicesContainer(
        profile_service=profile_service,
        auth_service=auth_service,
        job_service=job_service,
        file_saver_service=file_saver_service,
        analytics_service=analytics_service,
        process_chat_message_handler=process_chat_message_handler,
        new_job_processor=new_job_processor,
        chat_application_service=chat_components.application_service,
        billing_service=billing_service,
        admin_service=admin_service,
    )
