"""Единая форма ошибки сайдкара + обработчики фреймворка.

Форма одна на все сервисы платформы: `{"error": "<машинный код>", "detail": "<текст>"}`.
Коды объявлены в `service/contracts.py`.

⚠️ ЗАЧЕМ ОБРАБОТЧИКИ ФРЕЙМВОРКА. Без них сайдкар говорит ЧЕТЫРЬМЯ языками ошибок сразу:
наши ручки отдают `{"error","detail"}`, `HTTPException` — `{"detail": "..."}`, pydantic
на 422 — `{"detail": [{...}]}`, а непойманное исключение вообще уходит plain text'ом
«Internal Server Error» от starlette. Вызывающему пришлось бы уметь все четыре и
угадывать, какой пришёл.

⚠️ И ЗАЧЕМ ИСКЛЮЧЕНИЕ ДЛЯ `/v1`. Это чужой протокол: memos, ldr, graphify и любые
OpenAI-совместимые SDK ждут `{"error": {"message", "type"}}`. Навязать им нашу форму —
сломать совместимость ради единообразия внутри нашего же кода. Поэтому обработчики
пропускают `/v1` как есть.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from service.contracts import ERROR_CODES, MAX_BODY_BYTES, OPENAI_ERROR_PATH_PREFIX


def error(code: str, detail: str, status: int) -> JSONResponse:
    """Ответ об ошибке в единой форме. `code` обязан быть объявлен в контракте."""
    assert code in ERROR_CODES, f"код ошибки {code!r} не объявлен в contracts.ERROR_CODES"
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


def _is_openai_path(request: Request) -> bool:
    return request.url.path.startswith(OPENAI_ERROR_PATH_PREFIX)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if _is_openai_path(request):
        # Чужой протокол — отдаём его формой (см. докстринг модуля).
        return JSONResponse(
            {"error": {"message": str(exc.detail), "type": "invalid_request_error"}},
            status_code=exc.status_code,
        )
    code = {401: "unauthorized", 404: "not_found"}.get(exc.status_code, "internal")
    return error(code, str(exc.detail), exc.status_code)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    if _is_openai_path(request):
        return JSONResponse(
            {"error": {"message": str(exc.errors())[:400], "type": "invalid_request_error"}},
            status_code=422,
        )
    # Текст pydantic полезен вызывающему (он называет поле), но форма — наша.
    return error("invalid_request", str(exc.errors())[:400], 422)


async def body_size_limit_middleware(request: Request, call_next):
    """Отказать заранее, если вызывающий объявил слишком большое тело.

    ⚠️ ЛИМИТА НЕ БЫЛО ВООБЩЕ — ни на одной ручке сайдкара. Опаснее всего на `/run`: туда
    приезжают история переписки, память, резюме и извлечённый текст вложений, то есть
    тело растёт вместе с активностью пользователя. Не ограничивал никто: uvicorn читает
    тело целиком в память, а сайдкар ДОЛГОЖИВУЩИЙ и ОДИН на всю платформу — то есть
    один достаточно большой запрос кладёт обработку у всех сразу.

    Проверяем `Content-Length`. Он не покрывает chunked-передачу без заголовка, и это
    честное ограничение метода: полный разбор потребовал бы читать тело по кускам и
    считать самому, а это переписывание транспорта ради случая, которого у нас нет —
    все вызывающие шлют обычные запросы с длиной.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        if _is_openai_path(request):
            return JSONResponse(
                {
                    "error": {
                        "message": f"тело больше {MAX_BODY_BYTES} байт",
                        "type": "invalid_request_error",
                    }
                },
                status_code=413,
            )
        return error("request_too_large", f"тело больше {MAX_BODY_BYTES} байт", 413)
    return await call_next(request)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Непойманное исключение — тоже НАША форма, а не plain text от starlette.

    ⚠️ Молчаливый `Internal Server Error` строкой ломает вызывающего сильнее, чем сам
    сбой: он не может отличить «сервис упал» от «пришёл HTML прокси» — тело не разбирается
    ни как JSON, ни как код ошибки.
    """
    del exc
    if _is_openai_path(request):
        return JSONResponse(
            {"error": {"message": "internal", "type": "internal_error"}}, status_code=500
        )
    return error("internal", "internal", 500)
