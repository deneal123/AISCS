"""Транспорт сайдкара duckdb: контракт, коды ошибок, дедлайн.

Проверяется то, что до перевода на FastAPI не проверялось нечем, потому что и не
существовало: единая форма ошибки, объявленный контракт в `/health`, серверный дедлайн
и корректные коды на ошибку ВЫЗЫВАЮЩЕГО (415/422) против ошибки СЕРВИСА (500).

⚠️ Самый важный тест здесь — `test_timeout_is_not_reported_as_sql_error`. Ловушка не
очевидна: `duckdb.InterruptException` является ПОДКЛАССОМ `duckdb.Error`, поэтому без
преобразования в `core.QueryTimeout` наш собственный дедлайн уехал бы в ветку sql_error
и вернулся с кодом 200 — модель переписывала бы корректный SQL впустую. Проверено
мутацией: убрал преобразование в core — тест краснеет ровно этим сценарием.
"""

from __future__ import annotations

import base64

import contracts
import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def _file(name: str, content: str) -> dict:
    return {"name": name, "content_b64": base64.b64encode(content.encode()).decode()}


SALES = _file("sales.csv", "product,amount\nwidget,10\ngadget,20\n")


# --------------------------------------------------------------------------- #
# Контракт                                                                     #
# --------------------------------------------------------------------------- #
def test_health_publishes_contract():
    """`/health` обязан назвать себя и границы: с кем и на чём говорит вызывающий."""
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["service"] == contracts.SERVICE_NAME
    assert body["version"] == contracts.SERVICE_VERSION
    assert set(body["contract"]["response_fields"]) == set(contracts.RESPONSE_FIELDS)
    assert set(body["contract"]["error_codes"]) == set(contracts.ERROR_CODES)
    assert body["contract"]["max_body_bytes"] == contracts.MAX_BODY_BYTES
    assert body["contract"]["query_timeout_sec"] == contracts.QUERY_TIMEOUT_SEC


def test_success_response_matches_declared_fields():
    """Объявленный набор полей и реально отдаваемый — одно и то же.

    Список, живущий отдельно от кода, разъехался бы с ним и перестал что-либо
    гарантировать: вызывающий читает через `.get()` и молча получил бы пустоту.
    """
    body = client.post("/query", json={"sql": "SELECT 1 AS x", "files": [SALES]}).json()

    assert set(body) == set(contracts.RESPONSE_FIELDS)


# --------------------------------------------------------------------------- #
# Коды ошибок: вина вызывающего против вины сервиса                            #
# --------------------------------------------------------------------------- #
def test_unsupported_format_is_415_not_500():
    """Прислали .docx в аналитику таблиц — это 415, а не «у нас сломалось».

    Раньше `ValueError` из `core.load_file` проваливался в общий `except` и давал 500
    «query failed»: вина сваливалась на сервис, и вызывающий не мог понять, что чинить.
    """
    resp = client.post("/query", json={"files": [_file("doc.docx", "x")]})

    assert resp.status_code == 415
    assert resp.json()["error"] == "unsupported_format"


def test_bad_max_rows_is_422_not_500():
    """`{"max_rows": "abc"}` — ошибка схемы, а не сбой запроса.

    До pydantic-схемы это доезжало до `int()` в core и превращалось в 500.
    """
    resp = client.post("/query", json={"files": [SALES], "max_rows": "abc"})

    assert resp.status_code == 422


def test_no_files_is_400():
    resp = client.post("/query", json={"sql": "SELECT 1", "files": []})

    assert resp.status_code == 400
    assert resp.json()["error"] == "no_files"


def test_sql_error_stays_200_by_design():
    """Единственное отступление от «ошибка = не-2xx» — и оно намеренное.

    Неверный SQL не сбой транспорта: текст возвращается модели, чтобы она исправила
    запрос. Тест закрепляет это как РЕШЕНИЕ, а не как случайность.
    """
    resp = client.post("/query", json={"sql": "SELECT * FROM nope", "files": [SALES]})

    assert resp.status_code == 200
    assert resp.json()["error"] == "sql_error"


def test_framework_errors_speak_the_same_language():
    """404 и 422 от FastAPI обязаны иметь НАШУ форму, а не свою.

    ⚠️ Поймано живым прогоном, а не тестом: коды `not_found`/`invalid_request` были
    объявлены в контракте, но не отдавались никогда — фреймворк отвечал `{"detail": …}`
    и `{"detail": [ … ]}` в обход. Сервис говорил двумя языками ошибок сразу, и
    вызывающему пришлось бы уметь оба, то есть разбирать ответ угадыванием.
    """
    unknown = client.get("/no-such-route")
    assert unknown.status_code == 404
    assert unknown.json() == {"error": "not_found", "detail": unknown.json()["detail"]}
    assert unknown.json()["error"] in contracts.ERROR_CODES

    bad = client.post("/query", json={"files": [SALES], "max_rows": "abc"})
    assert bad.status_code == 422
    assert bad.json()["error"] == "invalid_request"
    assert bad.json()["error"] in contracts.ERROR_CODES


def test_every_error_code_is_declared():
    """Форма ошибки одна, и код обязан быть объявлен в контракте.

    Иначе вызывающий не сможет различать случаи: разбирать русский текст `detail`
    он не должен.
    """
    for payload, expected in (
        ({"files": [_file("doc.docx", "x")]}, "unsupported_format"),
        ({"files": []}, "no_files"),
    ):
        body = client.post("/query", json=payload).json()
        assert body["error"] == expected
        assert body["error"] in contracts.ERROR_CODES
        assert "detail" in body


# --------------------------------------------------------------------------- #
# Дедлайн                                                                      #
# --------------------------------------------------------------------------- #
def test_timeout_is_not_reported_as_sql_error(monkeypatch):
    """Наш дедлайн обязан приезжать как 504, а не как «поправь SQL» с кодом 200.

    ⚠️ Ровно та ловушка, ради которой заведён `core.QueryTimeout`:
    `duckdb.InterruptException` — подкласс `duckdb.Error`, и преобразование в
    `core.run_query` — единственное, что отличает «сервис не успел» от «модель
    ошиблась». Перепутать их значит заставить модель переписывать корректный запрос.

    Дедлайн подменяем на мизерный, а не ждём реальных 45 с: проверяется РЕАКЦИЯ
    транспорта, а не скорость DuckDB.
    """
    monkeypatch.setattr("core.QUERY_TIMEOUT_SEC", 0.001)

    resp = client.post(
        "/query",
        json={
            "sql": "SELECT count(*) FROM (SELECT range FROM range(60000000) ORDER BY random())",
            "files": [SALES],
        },
    )

    assert resp.status_code == 504
    assert resp.json()["error"] == "query_timeout"


def test_server_deadline_is_below_client_timeout():
    """Серверный дедлайн ОБЯЗАН быть меньше клиентского.

    Иначе клиент уходит по своему таймауту (60 с), а сервер продолжает считать запрос,
    написанный моделью: процессорное время горит без единого потребителя, и заметить
    это нечем. Клиентское значение — `agents.duckdb_timeout_sec`, дефолт 60.
    """
    assert contracts.QUERY_TIMEOUT_SEC < 60, (
        "дедлайн сайдкара должен быть строго меньше клиентского таймаута (60с), "
        f"сейчас {contracts.QUERY_TIMEOUT_SEC}"
    )


# --------------------------------------------------------------------------- #
# Корреляция                                                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("headers", [{}, {"X-Correlation-Id": "abc-123"}])
def test_correlation_header_is_optional(headers):
    """Заголовок принимается, но его отсутствие не ломает запрос.

    Сервис не должен падать из-за того, что вызывающий ещё не научился слать
    корреляцию: раскатка идёт по сервисам, а не одномоментно.
    """
    resp = client.post("/query", json={"sql": "SELECT 1 AS x", "files": [SALES]}, headers=headers)

    assert resp.status_code == 200
