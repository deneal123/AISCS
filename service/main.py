import logging
import logging.config

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from service.composition.models import AppContainer
from service.services.admin.presentation.routers.admin_api import admin_router
from service.services.analytics.presentation.routers.analytics_api.analytics_api import (
    analytics_router,
)
from service.services.analytics.presentation.routers.memory_api.memory_api import memory_router
from service.services.billing.presentation.routers.admin_billing_api import admin_billing_router
from service.services.billing.presentation.routers.billing_api import billing_router
from service.services.chat.presentation.http.files_overview_api import files_overview_router
from service.services.chat.presentation.http.graph_api import graph_router
from service.services.chat.presentation.routers.chat_api.chat_api import chat_router
from service.services.chat.presentation.routers.chat_ws import router as chat_ws_router
from service.services.chat.presentation.routers.workspace_coordination import (
    router as workspace_coordination_router,
)
from service.services.files.presentation.routers.files_api.files_api import files_router
from service.services.jobs.presentation.routers.jobs_api.jobs_api import jobs_router
from service.services.jobs.presentation.ws.jobs_ws import router as jobs_ws_router
from service.services.notifications.api import notifications_router
from service.services.notifications.presentation.user_events_ws import (
    router as user_events_ws_router,
)
from service.services.profile.presentation.routers.auth_api.auth_api import auth_router
from service.services.profile.presentation.routers.profile_api.profile_api import profile_router
from service.settings import LOGGING, config, redact_config_for_logging
from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from service.shared.presentation.routers.debug_api import router as debug_router
from service.utils.app_lifespan import lifespan

logging.config.dictConfig(LOGGING)
logger = logging.getLogger(__name__)
logger.info("config.initialized", extra={"config": redact_config_for_logging(config)})


_LOCAL_HOSTS = frozenset(
    {"", "localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal", "backend", "frontend"}
)
_LOCAL_SUFFIXES = (".local", ".localhost", ".test", ".internal")
_INSECURE_DEV_SECRET = "dev-insecure-secret-change-me"


def _domain_is_local(app_domain: str) -> bool:
    """True для локальных/dev-доменов (там dev-режим безопасен)."""
    host = str(app_domain or "").strip().lower()
    host = host.split("//")[-1].split("/")[0].split(":")[0]  # срезать схему/путь/порт
    if host in _LOCAL_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _LOCAL_SUFFIXES)


def _assert_prod_safety(cfg) -> None:
    """Fail-closed на старте: опасные dev-настройки на боевом домене запрещены.

    ``auth_mode=dev`` разблокирует анонимный WS-токен (фиксированный user 000…),
    dev test-token, insecure-cookie, CORS-localhost и debug-роутер. На публичном
    домене это дыра: при случайном ``AUTH__AUTH_MODE=dev`` в проде приложение НЕ
    должно подниматься. Отдельно ловим боевой запуск с известным dev-секретом
    (публично известный ключ подписи JWT). На localhost/*.local/*.test/*.internal
    dev-режим разрешён — это обычная разработка.
    """
    # Секция auth стала НЕОБЯЗАТЕЛЬНОЙ в общем ядре: сайдкару агентов она не нужна, и он
    # больше не подаёт фейковый JWT-секрет ради конструирования Config. Но backend без
    # неё работать не может, а проверки ниже защитные (getattr с дефолтами) — они бы
    # пропустили старт, и падение случилось бы на ПЕРВОМ входе пользователя. Требуем явно.
    from service.settings import require_auth

    require_auth(cfg)

    auth = getattr(cfg, "auth", None)
    service = getattr(cfg, "service", None)
    auth_mode = str(getattr(auth, "auth_mode", "prod") or "prod").strip().lower()
    app_domain = str(getattr(service, "app_domain", "") or "")
    secret = str(getattr(auth, "secret", "") or "").strip()

    if auth_mode == "dev" and not _domain_is_local(app_domain):
        raise RuntimeError(
            f"AUTH__AUTH_MODE=dev на боевом домене SERVICE__APP_DOMAIN={app_domain!r}: "
            "dev-режим включает анонимный WS-токен, dev test-token, insecure-cookie, "
            "CORS-localhost и debug-роутер — это запрещено в проде. Установите "
            "AUTH__AUTH_MODE=prod (с полноценными секретами) либо запускайте dev только "
            "на локальном домене."
        )

    if auth_mode == "prod" and secret == _INSECURE_DEV_SECRET:
        raise RuntimeError(
            "AUTH__SECRET равен известному dev-дефолту при AUTH__AUTH_MODE=prod: "
            "JWT подписывались бы публично известным ключом. Задайте уникальный секрет."
        )

    # dev_mode — ОТДЕЛЬНЫЙ флаг, управляющий secure/samesite куки (auth_api). Он может
    # разойтись с auth_mode: AUTH__DEV_MODE=true при AUTH__AUTH_MODE=prod отдавал бы куку
    # Secure=False; SameSite=lax на боевом домене (перехват/CSRF-послабление), а проверка
    # выше смотрит только auth_mode и это не ловила. Фейлим комбинацию явно.
    if auth_mode == "prod" and bool(getattr(auth, "dev_mode", False)):
        raise RuntimeError(
            "AUTH__DEV_MODE=true при AUTH__AUTH_MODE=prod: сессионная кука ушла бы "
            "Secure=False/SameSite=lax на боевом домене. Уберите AUTH__DEV_MODE (в проде "
            "куку защищает auth_mode=prod)."
        )

    # LLM-шлюз с ПУСТЫМ ключом = открытый /v1 (любой запрос тарифит наш бюджет провайдеров).
    # В dev это внутренний режим docker-сети, но при auth_mode=prod пустой ключ — это тихая
    # утечка всего LLM-бюджета из-за забытой переменной. Фейлим старт, как и прочие dev-послабления.
    agents = getattr(cfg, "agents", None)
    gateway_on = bool(getattr(agents, "llm_gateway_enabled", False))
    gateway_key = str(getattr(agents, "llm_gateway_api_key", "") or "").strip()
    if auth_mode == "prod" and gateway_on and not gateway_key:
        raise RuntimeError(
            "AGENTS__LLM_GATEWAY_ENABLED=true с пустым AGENTS__LLM_GATEWAY_API_KEY при "
            "AUTH__AUTH_MODE=prod: /v1-шлюз был бы открыт без аутентификации — любой запрос "
            "тарифил бы наш бюджет провайдеров. Задайте ключ шлюза либо выключите шлюз в проде."
        )


def create_app(container_override: AppContainer | None = None) -> FastAPI:
    _assert_prod_safety(config)
    service_title = (getattr(config.service, "name", "") or "").strip() or "GPTHub API"
    app = FastAPI(
        title=service_title,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url="/api/redoc",
    )

    if container_override is not None:
        app.state.container = container_override

    cors_config = getattr(config, "cors", None)
    allow_origins = getattr(cors_config, "allow_origins", []) if cors_config else []
    auth_mode = str(getattr(getattr(config, "auth", None), "auth_mode", "prod")).strip().lower()
    is_dev_mode = auth_mode == "dev"

    if allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif is_dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3001",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        raise RuntimeError(
            "CORS_ALLOW_ORIGINS must be configured in production mode (AUTH__AUTH_MODE=prod)."
        )

    app.include_router(auth_router, tags=["Auth-API"])
    app.include_router(jobs_router, tags=["Jobs-API"])
    app.include_router(files_router, tags=["Files-API"])
    app.include_router(profile_router, tags=["Profile-API"])
    app.include_router(chat_ws_router, tags=["Chat-WS"])
    app.include_router(jobs_ws_router, tags=["Jobs-WS"])
    app.include_router(user_events_ws_router, tags=["User-Events-WS"])
    if is_dev_mode:
        app.include_router(debug_router, tags=["Debug"])
    app.include_router(chat_router, tags=["Chat-API"])
    # The workspace sidecar is intentionally outside the user-facing chat
    # prefix.  Its signed coordinator contract is service-to-service only.
    app.include_router(workspace_coordination_router, tags=["Workspace-Coordination"])
    app.include_router(memory_router, tags=["Memory-API"])
    app.include_router(graph_router, tags=["Graph-API"])
    # Обзор файлов аккаунта — ОТДЕЛЬНОЕ окно от рабочего каталога треда: тот временный и
    # привязан к песочнице, этот накопительный и только на чтение.
    app.include_router(files_overview_router, tags=["Files-Overview"])
    app.include_router(notifications_router, tags=["Notifications"])
    app.include_router(analytics_router, tags=["Analytics-API"])
    app.include_router(billing_router, tags=["Billing-API"])
    app.include_router(admin_billing_router, tags=["Admin-Billing-API"])
    app.include_router(admin_router, tags=["Admin-API"])
    # /v1-шлюз БОЛЬШЕ НЕ ЗДЕСЬ: им владеет сайдкар agents (он единственный, кто ходит
    # к провайдерам). memos/ldr/graphify переведены на http://agents:8090/v1 тем же
    # ключом. Держать второй шлюз в backend значило бы иметь две точки, тарифящие
    # бюджет провайдеров, с разным представлением о том, кто из них жив.

    setup_exception_handlers(app)

    @app.get("/api/health", include_in_schema=False)
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Expose bounded Prometheus metrics for the existing monitoring scraper."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

    return app


app = create_app()
