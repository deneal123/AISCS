"""Сайдкар говорит ОДНОЙ формой ошибки — кроме `/v1`, и это названное исключение.

⚠️ До этих обработчиков форм было ЧЕТЫРЕ сразу:
  * наши ручки — `{"error", "detail"}`;
  * `HTTPException` (401/404) — `{"detail": "..."}`;
  * pydantic на 422 — `{"detail": [{...}]}`;
  * непойманное исключение — вообще plain text «Internal Server Error» от starlette.

Вызывающему пришлось бы уметь все четыре и угадывать, какая пришла. Хуже всего
последняя: тело не разбирается ни как JSON, ни как код, и «сервис упал» не отличить от
«ответил прокси».

⚠️ `/v1` ОСТАЁТСЯ на OpenAI-форме намеренно: это чужой протокол, его клиенты (memos, ldr,
graphify, любые SDK) ждут `{"error": {"message", "type"}}`. Единообразие внутри нашего
кода не стоит сломанной совместимости.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from service import contracts
from service.presentation import errors

KEY = "test-internal-key"


@pytest.fixture()
def app_with_handlers():
    """Приложение с теми же обработчиками, что и боевое (см. service/main.py)."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, errors.http_exception_handler)
    app.add_exception_handler(RequestValidationError, errors.validation_exception_handler)
    app.add_exception_handler(Exception, errors.unhandled_exception_handler)

    class Body(BaseModel):
        n: int

    @app.post("/ours/schema")
    async def _schema(_body: Body) -> dict:
        return {"ok": True}

    @app.get("/ours/boom")
    async def _boom() -> dict:
        raise RuntimeError("внутренний сбой")

    @app.get("/ours/denied")
    async def _denied() -> dict:
        raise HTTPException(status_code=401, detail="invalid key")

    @app.post("/v1/chat/completions")
    async def _v1(_body: Body) -> dict:
        return {"ok": True}

    @app.get("/v1/boom")
    async def _v1_boom() -> dict:
        raise RuntimeError("внутренний сбой")

    return app


def _client(app):
    # raise_server_exceptions=False — иначе TestClient поднимет исключение у себя и
    # обработчик 500 не отработает, то есть тест проверял бы не то.
    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_uses_our_form(app_with_handlers):
    resp = _client(app_with_handlers).get("/no-such-route")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"
    assert "detail" in resp.json()


def test_http_exception_uses_our_form(app_with_handlers):
    resp = _client(app_with_handlers).get("/ours/denied")

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_validation_error_uses_our_form(app_with_handlers):
    resp = _client(app_with_handlers).post("/ours/schema", json={"n": "не число"})

    assert resp.status_code == 422
    assert resp.json()["error"] == "invalid_request"


def test_unhandled_exception_is_json_not_plain_text(app_with_handlers):
    """Непойманное исключение обязано быть JSON с кодом, а не строкой от starlette.

    Строка ломает вызывающего сильнее самого сбоя: он не может отличить «сервис упал»
    от «ответил прокси» — тело не разбирается ни как JSON, ни как код.
    """
    resp = _client(app_with_handlers).get("/ours/boom")

    assert resp.status_code == 500
    assert resp.json()["error"] == "internal"


@pytest.mark.parametrize("code", sorted(contracts.ERROR_CODES))
def test_every_declared_code_is_usable(code):
    """Каждый объявленный код можно отдать. Иначе контракт обещает несуществующее."""
    resp = errors.error(code, "детали", 500)

    assert resp.status_code == 500


def test_undeclared_code_is_a_programming_error():
    """Код не из контракта — падение на месте, а не тихая отправка выдумки.

    Иначе список кодов в `/health` разошёлся бы с тем, что сервис реально отдаёт, и
    вызывающий строил бы обработку по несуществующим значениям.
    """
    with pytest.raises(AssertionError):
        errors.error("выдуманный_код", "детали", 500)


# --------------------------------------------------------------------------- #
# Названное исключение: /v1 остаётся на чужом протоколе                        #
# --------------------------------------------------------------------------- #
def test_v1_keeps_openai_error_shape_on_validation(app_with_handlers):
    resp = _client(app_with_handlers).post("/v1/chat/completions", json={"n": "не число"})

    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body["error"], dict), "у /v1 ошибка ОБЪЕКТ, как ждёт OpenAI-SDK"
    assert "message" in body["error"] and "type" in body["error"]


def test_v1_keeps_openai_error_shape_on_crash(app_with_handlers):
    resp = _client(app_with_handlers).get("/v1/boom")

    assert resp.status_code == 500
    assert isinstance(resp.json()["error"], dict)


def test_v1_prefix_is_declared_in_contract():
    """Исключение записано в контракте, а не спрятано в коде обработчика."""
    assert contracts.OPENAI_ERROR_PATH_PREFIX == "/v1"
