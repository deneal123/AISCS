#!/usr/bin/env python3
"""Транспорт сайдкара duckdb: SQL/аналитика по загруженным табличным файлам.

Логика — в `core.py`, границы контракта — в `contracts.py`; здесь только HTTP.

  POST /query   {"sql": "<опц.; пусто → схема+превью>",
                 "files": [{name, content_b64}], "max_rows": 200}
                → {"sql","columns","rows","row_count","truncated","tables","duration_sec"}
  GET  /health  → {"status","service","version","contract"}
  GET  /formats → {"formats": [...]}

Форма ошибки одна на все сервисы: `{"error": "<машинный код>", "detail": "<текст>"}`.
Коды — в `contracts.ERROR_CODES`; вызывающий различает по `error`, а не по тексту.

⚠️ ЕДИНСТВЕННОЕ отступление от «ошибка = не-2xx»: неверный SQL отдаётся с HTTP 200 и
телом `{"error": "sql_error", ...}`. Это не сбой транспорта, а нормальный ход диалога —
текст ошибки возвращается модели, чтобы она исправила запрос. Отступление названо явно
здесь и в контракте, чтобы отличаться от недосмотра.

Почему DuckDB, а не тяжёлый Velox/Axiom: один pip-пакет, нативно читает
csv/tsv/parquet/json, встраивается, изолируется. xlsx читаем через openpyxl → csv
(DuckDB сам выведет типы) — расширение `excel` тянуть по сети нельзя: сайдкар на
internal-сети без интернета.
"""

import logging
import os

import duckdb
import uvicorn
from contracts import (
    ERROR_CODES,
    MAX_BODY_BYTES,
    QUERY_TIMEOUT_SEC,
    RESPONSE_FIELDS,
    SERVICE_NAME,
    SERVICE_VERSION,
)
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import (
    DEFAULT_MAX_ROWS,
    HARD_MAX_ROWS,
    SUPPORTED_EXT,
    QueryTimeout,
    UnsupportedFormat,
    run_query,
)

PORT = int(os.environ.get("PORT", "8080"))

logger = logging.getLogger("duckdb-sidecar")

app = FastAPI(title="GPTHub duckdb sidecar", version=SERVICE_VERSION, docs_url=None, redoc_url=None)


def _error(code: str, detail: str, status: int) -> JSONResponse:
    """Единая форма ошибки. `code` обязан быть объявлен в контракте."""
    assert code in ERROR_CODES, f"код ошибки {code!r} не объявлен в contracts.ERROR_CODES"
    return JSONResponse({"error": code, "detail": detail}, status_code=status)


# ⚠️ ОБРАБОТЧИКИ ФРЕЙМВОРКА — ЧАСТЬ КОНТРАКТА, А НЕ КОСМЕТИКА. Без них FastAPI отдаёт
# СВОЮ форму (`{"detail": ...}` на 404 и `{"detail": [...]}` на 422), и сервис говорит
# двумя разными языками ошибок сразу: наши ручки — `{"error","detail"}`, а фреймворк —
# по-своему. Вызывающий тогда обязан уметь оба, то есть разбирать ответ угадыванием.
# Живой прогон это и показал: коды `not_found`/`invalid_request` были объявлены в
# контракте, но не отдавались никогда.
@app.exception_handler(StarletteHTTPException)
async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "query_failed"
    return _error(code, str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Текст pydantic полезен вызывающему (он называет поле), но форма — наша.
    return _error("invalid_request", str(exc.errors())[:400], 422)


class FileIn(BaseModel):
    name: str = ""
    content_b64: str = ""


class QueryIn(BaseModel):
    """Схема запроса.

    ⚠️ До неё тело разбиралось вручную и типы не проверялись: `{"max_rows": "abc"}`
    доезжал до `int()` в core и превращался в 500 «query failed» — то есть ошибка
    ВЫЗЫВАЮЩЕГО выглядела как поломка сервиса. Теперь это 422 с указанием поля.
    """

    sql: str = ""
    files: list[FileIn] = Field(default_factory=list)
    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=1, le=HARD_MAX_ROWS)


@app.get("/health")
async def health() -> dict:
    """Хелсчек + публикация контракта: с кем именно говорит вызывающий.

    `contract` — ИМЕНА, а не счётчики: «7 полей» совпадёт и при разных наборах.
    Сверяется офлайн-гейтом `scripts/check_contract_parity.py`.
    """
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "duckdb": duckdb.__version__,
        "contract": {
            "response_fields": sorted(RESPONSE_FIELDS),
            "error_codes": sorted(ERROR_CODES),
            "max_body_bytes": MAX_BODY_BYTES,
            "query_timeout_sec": QUERY_TIMEOUT_SEC,
            "formats": list(SUPPORTED_EXT),
        },
    }


@app.get("/formats")
async def formats() -> dict:
    return {"formats": list(SUPPORTED_EXT)}


@app.post("/query")
async def query(
    payload: QueryIn,
    request: Request,
    correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
) -> JSONResponse:
    # Сквозной идентификатор — единственное, что связывает строку в логе сайдкара с
    # сообщением пользователя в логе backend'а. Заголовка нет — работаем, но помечаем:
    # молча терять связь хуже, чем знать, что её нет.
    cid = correlation_id or "-"

    length = int(request.headers.get("content-length") or 0)
    if length > MAX_BODY_BYTES:
        return _error("request_too_large", f"тело больше {MAX_BODY_BYTES} байт", 413)
    if not payload.files:
        return _error("no_files", "не передано ни одного файла", 400)

    try:
        result = run_query(payload.sql, [f.model_dump() for f in payload.files], payload.max_rows)
    except UnsupportedFormat as exc:
        return _error("unsupported_format", str(exc), 415)
    except QueryTimeout as exc:
        logger.warning("[cid=%s] дедлайн запроса исчерпан: %s", cid, exc)
        return _error("query_timeout", str(exc), 504)
    except duckdb.Error as exc:
        # ⚠️ Сюда НЕ должен попадать наш дедлайн. `duckdb.InterruptException` —
        # подкласс `duckdb.Error`, и без преобразования в `core.QueryTimeout` он
        # приехал бы именно в эту ветку: модель получила бы «поправь SQL» с кодом 200
        # на наш собственный таймаут и переписывала бы корректный запрос впустую.
        # Само преобразование живёт в `core.run_query` — там же, где его видно.
        return JSONResponse(
            {"error": "sql_error", "detail": str(exc)[-600:], "sql": payload.sql}, status_code=200
        )
    except Exception as exc:  # defensive: любой сбой → нет результата
        logger.exception("[cid=%s] запрос не выполнен", cid)
        return _error("query_failed", str(exc)[-400:], 500)

    return JSONResponse(result)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info(
        "duckdb-sidecar on :%s | contract=%s | duckdb=%s | formats=%d | timeout=%gs",
        PORT,
        SERVICE_VERSION,
        duckdb.__version__,
        len(SUPPORTED_EXT),
        QUERY_TIMEOUT_SEC,
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
