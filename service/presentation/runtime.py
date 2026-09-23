"""Загрузка движка на СТАРТЕ и единый ответ на вопрос «что доступно».

Сайдкар существует ради движка, поэтому его отсутствие лучше увидеть в `/health`,
чем на первом запросе. Но процесс НЕ роняем: тогда healthcheck и диагностика
остаются живыми, а причина видна снаружи.

Почему одно место, а не try/except в каждом обработчике: именно так однажды пропал
`POST /route` — импорт стоял ВНУТРИ ручки под широким `except`, отсутствующий модуль
превратился в вечную «деградацию», и никто этого не заметил. Ошибка выкладки должна
быть видна в одном месте, а не растворяться по обработчикам.

ВАЖНО про движок: берём ``DefaultAgentExecutionService`` НАПРЯМУЮ, а не через фабрику
``select_agent_engine`` — фабрика умеет вернуть HTTP-движок, а сайдкар это ТЕРМИНАЛЬНАЯ
точка исполнения (получили бы рекурсию сайдкар→сайдкар).
"""

from __future__ import annotations

ENGINE_ERROR: str | None = None
try:
    from service.application.agent_execution_service import (
        DefaultAgentExecutionService,
    )
except Exception:  # noqa: BLE001 — диагностируем через /health, не падаем
    DefaultAgentExecutionService = None  # type: ignore[assignment]
    ENGINE_ERROR = "startup_failure"

# OpenAI-совместимый шлюз `/v1` (chat/completions, models, embeddings) — тот самый,
# что зовут memos/ldr/graphify. Живёт В ДВИЖКЕ (presentation/routers) и опирается на
# мультипровайдерный слой, который у сайдкара есть, — поэтому просто монтируем готовый.
GATEWAY_ERROR: str | None = None
try:
    from service.presentation.routers.gateway.openai_v1 import v1_router
except Exception:  # noqa: BLE001
    v1_router = None  # type: ignore[assignment]
    GATEWAY_ERROR = "startup_failure"

ROUTING_ERROR: str | None = None
try:
    from service.application.model_routing_service import (
        ModelRoutingError,
        ModelRoutingService,
    )
except Exception:  # noqa: BLE001
    ModelRoutingService = None  # type: ignore[assignment]
    ModelRoutingError = RuntimeError  # type: ignore[misc,assignment]
    ROUTING_ERROR = "startup_failure"


def vector_store():
    """Модуль векторного хранилища; ``None`` — движок не подан."""
    try:
        from service.domain.tools import vector_store as store

        return store
    except Exception:  # noqa: BLE001
        return None


def known_provider_names() -> list[str]:
    """Имена провайдеров из реестра движка; пусто, если движок не подан."""
    try:
        from service.domain.client.registry import PROVIDER_MODULES

        return list(PROVIDER_MODULES.keys())
    except Exception:  # noqa: BLE001
        return []
