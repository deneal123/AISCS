import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from service.shared.error_handling.error_mapper import (
    map_exception_to_error_response,
    map_exception_to_status,
)
from service.shared.error_handling.exceptions import RateLimitedError
from service.shared.repositories.exceptions import RepositoryError

logger = logging.getLogger(__name__)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    logger.warning(
        "HTTP Exception occurred: %s - %s for request: %s %s",
        exc.status_code,
        exc.detail,
        request.method,
        request.url,
    )
    payload = map_exception_to_error_response(exc)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # НЕ логируем exc.errors() целиком и НЕ эхоим error["input"] обратно — там сырые
    # значения полей запроса (напр. plaintext-пароль с /register) → утечка PII/секретов
    # в логи и в ответ. В лог — только пути полей и типы ошибок (без значений).
    safe_fields = [
        {
            "field": ".".join(str(loc) for loc in error.get("loc", ())),
            "type": error.get("type"),
        }
        for error in exc.errors()
    ]
    logger.warning(
        "Validation error for request %s %s: %s",
        request.method,
        request.url,
        safe_fields,
    )
    errors = [
        {
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    exception = HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "validation_error",
            "message": "Validation error",
            "type": "ValidationError",
            "details": errors,
        },
    )
    payload = map_exception_to_error_response(exception)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump()
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception occurred for request: %s %s", request.method, request.url)
    status_code = map_exception_to_status(exc)
    payload = map_exception_to_error_response(exc)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def repository_exception_handler(request: Request, exc: RepositoryError) -> JSONResponse:
    status_code = map_exception_to_status(exc)
    logger.warning(
        "%s occurred for request %s %s: %s",
        exc.__class__.__name__,
        request.method,
        request.url,
        exc,
    )
    payload = map_exception_to_error_response(exc)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def rate_limited_exception_handler(request: Request, exc: RateLimitedError) -> JSONResponse:
    logger.warning(
        "Rate limited: %s %s (retry_after=%s)", request.method, request.url, exc.retry_after
    )
    payload = map_exception_to_error_response(exc)
    retry_after = max(0, int(getattr(exc, "retry_after", 0) or 0))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=payload.model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


def setup_exception_handlers(app: FastAPI):
    app.add_exception_handler(RateLimitedError, rate_limited_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )  # type: ignore[arg-type]
    app.add_exception_handler(RepositoryError, repository_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, general_exception_handler)  # type: ignore[arg-type]
