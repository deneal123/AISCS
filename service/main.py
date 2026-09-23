#!/usr/bin/env python3
"""agents — сайдкар агентного движка GPTHub (FastAPI).

Исполняет агентский пайплайн в ДОЛГОЖИВУЩЕМ процессе — в отличие от celery
loop-per-task в backend, где это регулярно ломало модульные async-примитивы.

Сервис владеет провайдерами: все LLM-вызовы платформы идут через него, включая
OpenAI-совместимый шлюз `/v1`, которым пользуются memos/ldr/graphify. Состояния
backend'а (PG/Redis/MinIO) у него нет по устройству — история, память, резюме и
ссылки на файлы приезжают В ТЕЛЕ запроса, которое backend собирает сам.

Контракт, обязанный совпадать у обеих сторон, объявлен в `service/contracts.py` и
сверяется офлайн-гейтом суперпроекта. Клиенты соседних сервисов, наоборот, у каждого
свои — общего пакета нет намеренно.

Этот файл — ТОЛЬКО сборка приложения. Сами ручки живут в `service/presentation/routers/`
(см. докстринг того пакета: там же и группировка по назначению).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from service.presentation import errors, runtime
from service.presentation.routers import ALL_ROUTERS


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Fail startup when the source-controlled capability graph is inconsistent."""

    from service.domain.capabilities.compiler import CapabilityConfigurationError
    from service.domain.capabilities.metrics import record
    from service.domain.capabilities.runtime import initialize_static_catalog

    try:
        catalog = initialize_static_catalog()
    except CapabilityConfigurationError as exc:
        record("startup", "failed", exc.code)
        raise
    app.state.capability_catalog = catalog
    try:
        yield
    finally:
        from service.domain.client.registry import drain_provider_generations

        await drain_provider_generations()


app = FastAPI(title="gpthub-agents-sidecar", version="0.1.0", lifespan=_lifespan)

# ⚠️ Лимит тела ПЕРВЫМ: смысл в том, чтобы огромное тело не дошло ни до авторизации, ни
# до pydantic. Его не было ни на одной ручке, а сайдкар долгоживущий и один на всю
# платформу — один достаточно большой запрос клал бы обработку у всех сразу.
app.middleware("http")(errors.body_size_limit_middleware)

# ⚠️ Единая форма ошибки для ВСЕГО сервиса. Без этих трёх обработчиков сайдкар говорит
# четырьмя языками сразу: наши ручки — `{"error","detail"}`, HTTPException —
# `{"detail": "..."}`, pydantic — `{"detail": [...]}`, а непойманное исключение уходит
# plain text'ом от starlette. `/v1` из этого исключён намеренно: там чужой протокол,
# и его клиенты ждут OpenAI-форму (см. service/presentation/errors.py).
app.add_exception_handler(StarletteHTTPException, errors.http_exception_handler)
app.add_exception_handler(RequestValidationError, errors.validation_exception_handler)
app.add_exception_handler(Exception, errors.unhandled_exception_handler)

# Список ОДИН и живёт рядом с самими ручками. Перечислять их ещё и здесь значило бы
# завести второе место, где о новой ручке надо помнить, — а забытая ручка не существует.
for _router in ALL_ROUTERS:
    app.include_router(_router)

# Шлюз монтируем последним и только если он загрузился: движка может не быть (сборка,
# отсутствующий маунт), и тогда сайдкар всё равно должен подняться — с живым /health,
# где видно, почему шлюз недоступен. Падать здесь значило бы лишить себя диагностики.
if runtime.v1_router is not None:
    app.include_router(runtime.v1_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8090")))
