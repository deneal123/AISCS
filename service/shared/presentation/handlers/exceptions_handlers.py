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

from .http_failure_boundary import HttpFailureBoundary, HttpResponseAborted
from .validation_feedback import validation_feedback

logger = logging.getLogger(__name__)


def _log_failure(code: str, status_code: int) -> None:
    # Request paths, validation locations and exception bodies are untrusted.
    logger.warning(
        "HTTP request failed: %s (%s)",
        code,
        status_code,
        extra={"component": "http_boundary", "failure_code": code, "status_code": status_code},
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    _log_failure("http", exc.status_code)
    payload = map_exception_to_error_response(exc)
    return JSONResponse(
        status_code=exc.status_code, content=payload.model_dump(), headers=exc.headers
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # НЕ логируем exc.errors() целиком и НЕ эхоим error["input"] обратно — там сырые
    # значения полей запроса (напр. plaintext-пароль с /register) → утечка PII/секретов
    # в логи и в ответ. Даже loc может содержать пользовательский ключ:
    # в лог передаём только bounded category, без полей/сообщений валидатора.
    _log_failure("validation", status.HTTP_422_UNPROCESSABLE_ENTITY)
    errors = validation_feedback(request, exc.errors())
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
    status_code = map_exception_to_status(exc)
    if not isinstance(exc, HttpResponseAborted):
        _log_failure("internal", status_code)
    payload = map_exception_to_error_response(exc)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def repository_exception_handler(request: Request, exc: RepositoryError) -> JSONResponse:
    status_code = map_exception_to_status(exc)
    _log_failure("repository", status_code)
    payload = map_exception_to_error_response(exc)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def rate_limited_exception_handler(request: Request, exc: RateLimitedError) -> JSONResponse:
    _log_failure("rate_limited", status.HTTP_429_TOO_MANY_REQUESTS)
    payload = map_exception_to_error_response(exc)
    retry_after = max(0, int(getattr(exc, "retry_after", 0) or 0))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=payload.model_dump(),
        headers={"Retry-After": str(retry_after)},
    )


def setup_exception_handlers(app: FastAPI):
    app.add_middleware(
        HttpFailureBoundary,
        error_handler=general_exception_handler,
        failure_reporter=_log_failure,
    )
    app.add_exception_handler(RateLimitedError, rate_limited_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )  # type: ignore[arg-type]
    app.add_exception_handler(RepositoryError, repository_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, general_exception_handler)  # type: ignore[arg-type]
