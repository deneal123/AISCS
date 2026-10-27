import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from service.composition.container import build_container
from service.composition.state import get_current_container, set_current_container
from service.settings import Config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting application...")

    try:
        config = Config()
        app_container = getattr(app.state, "container", None)
        if app_container is None:
            logger.info("Building dependency container...")
            app_container = build_container(config)
            app.state.container = app_container
        set_current_container(app_container)

        logger.info("Initializing database...")
        await app_container.infra.pg_connector.verify_connection()
        logger.info("Database connection verified")

        if config.service.application_profile == "simulation":
            # The same auth/storage/container are reused; chat, pricing and IDE loops stay idle.
            logger.info("Simulation profile ready")
            yield
            return

        # Гидрация runtime-ключей провайдеров из БД (замены, сделанные из админки,
        # переживают рестарт). Fail-soft: провайдеры и без этого поднимаются на env.
        try:
            from service.services.admin.application.provider_key_service import ProviderKeyService

            applied = await ProviderKeyService().hydrate_all()
            if applied:
                logger.info("Hydrated %s provider key override(s) from DB", applied)
        except Exception:
            logger.warning(
                "Provider key hydration skipped",
                extra={"component": "provider_hydration", "failure_code": "unavailable"},
            )

        logger.info("Starting background task manager...")
        task_manager = app_container.infra.background_task_manager
        await task_manager.start()

        from service.services.chat.application.ide.commands.recovery import command_reconciliation

        await task_manager.start_task_with_restart(
            lambda: command_reconciliation(app_container.infra),
            task_name="ide-command-reconciliation",
            restart_delay=5,
        )

        try:
            await task_manager.start_task_with_restart(
                app_container.services.new_job_processor.process_new_jobs,
                task_name="new-jobs-processor",
                restart_delay=5,
            )
        except Exception:
            logger.warning("Job processor is not available; background processing disabled")

        try:
            from service.utils.file_scan_worker import scan_loop

            await task_manager.start_task_with_restart(
                scan_loop,
                task_name="file-scan-loop",
                restart_delay=5,
            )
        except Exception:
            logger.warning("File scanner loop is not available; file scanning disabled")

        # Восстановить persistent health-блоки провайдеров из БД в Redis+память (переживают
        # рестарт: заблокированный остаётся заблокированным до успешной переспроверки).
        try:
            from service.infrastructure import provider_policy_store as provider_policy

            await provider_policy.prime()
        except Exception:
            logger.debug(
                "Provider policy prime failed",
                extra={"component": "provider_policy", "failure_code": "unavailable"},
            )

        # Прогрев кэша статуса провайдеров: живые пробы мёртвых тянутся до таймаута, и без
        # прогрева ПЕРВЫЙ показ админ-панели ждал бы их. Фоном, чтобы не тормозить старт.
        try:
            import asyncio

            asyncio.create_task(app_container.services.admin_service.prime_provider_health())
        except Exception:
            logger.debug(
                "Provider health prime not scheduled",
                extra={"component": "provider_health", "failure_code": "unavailable"},
            )

        logger.info("Application started successfully!")
        yield

    except Exception:
        logger.error(
            "Application lifecycle unavailable",
            extra={"component": "application_startup", "failure_code": "unavailable"},
        )
        raise RuntimeError("startup_unavailable") from None

    finally:
        logger.info("Shutting down application...")

        try:
            active_container = getattr(app.state, "container", None) or get_current_container()
            logger.info("Stopping background task manager...")
            try:
                await active_container.infra.background_task_manager.stop()
            finally:
                logger.info("Closing database connections...")
                await active_container.infra.pg_connector.close()
            logger.info("Application shut down gracefully")

        except Exception:
            logger.error(
                "Application cleanup unavailable",
                extra={"component": "application_shutdown", "failure_code": "unavailable"},
            )


async def health_check():
    try:
        app_container = get_current_container()
        await app_container.infra.pg_connector.verify_connection()

        return {
            "status": "healthy",
            "database": "connected",
            "version": "1.0.0",
        }

    except Exception:
        logger.error(
            "Health check failed",
            extra={"component": "application_health", "failure_code": "unavailable"},
        )
        return {"status": "unhealthy", "error": "unavailable", "version": "1.0.0"}
