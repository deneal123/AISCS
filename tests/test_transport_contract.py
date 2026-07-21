"""Транспорт сайдкара opendataloader: контракт, коды ошибок, ДЕЙСТВУЮЩИЙ дедлайн.

⚠️ Главное здесь — `test_parse_timeout_is_actually_applied`. `ODL_PARSE_TIMEOUT_SEC`
объявлялся в трёх местах (contracts, Dockerfile ENV, оба compose), пробрасывался в
контейнер — и НЕ ПРИМЕНЯЛСЯ НИ РАЗУ: вызов `opendataloader_pdf.convert` шёл без
ограничения по времени, потому что поток с JVM не прервать. Настройка выглядела рабочей
и не делала ничего.
"""

from __future__ import annotations

import subprocess

import contracts
import pytest
from fastapi.testclient import TestClient

import app


@pytest.fixture()
def client():
    return TestClient(app.app)


# --------------------------------------------------------------------------- #
# Контракт                                                                     #
# --------------------------------------------------------------------------- #
def test_health_publishes_contract(client):
    body = client.get("/health").json()

    assert body["service"] == contracts.SERVICE_NAME
    assert body["version"] == contracts.SERVICE_VERSION
    assert set(body["contract"]["error_codes"]) == set(contracts.ERROR_CODES)
    assert set(body["contract"]["response_fields"]) == set(contracts.RESPONSE_FIELDS)


# --------------------------------------------------------------------------- #
# Коды ошибок                                                                  #
# --------------------------------------------------------------------------- #
def test_unsupported_format_is_415(client):
    resp = client.post("/parse?filename=picture.png", content=b"data")

    assert resp.status_code == 415
    assert resp.json()["error"] == "unsupported_format"


def test_empty_body_is_400(client):
    resp = client.post("/parse?filename=doc.pdf", content=b"")

    assert resp.status_code == 400
    assert resp.json()["error"] == "empty_body"


def test_too_large_body_is_413(client, monkeypatch):
    monkeypatch.setattr(app, "MAX_BODY_BYTES", 10)

    resp = client.post("/parse?filename=doc.pdf", content=b"x" * 100)

    assert resp.status_code == 413
    assert resp.json()["error"] == "request_too_large"


def test_convert_rejects_non_spreadsheet_with_415(client):
    resp = client.post("/convert?filename=doc.pdf", content=b"data")

    assert resp.status_code == 415
    assert resp.json()["error"] == "unsupported_format"


def test_unknown_route_speaks_our_error_form(client):
    resp = client.get("/no-such-route")

    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


# --------------------------------------------------------------------------- #
# Дедлайн                                                                      #
# --------------------------------------------------------------------------- #
def test_parse_timeout_is_actually_applied(client, monkeypatch):
    """Дедлайн парсера ДЕЙСТВУЕТ и приезжает как 504.

    ⚠️ До перевода на подпроцесс ограничить парсер было нечем: `opendataloader_pdf.convert`
    исполнялся в нашем процессе, а поток с JVM не прерывается. Настройка существовала
    только на бумаге. Теперь это `subprocess.run(..., timeout=…)`, и таймаут реален.
    """

    def _timeout(*_a, **_kw):
        raise subprocess.TimeoutExpired(cmd="parse", timeout=contracts.PARSE_TIMEOUT_SEC)

    monkeypatch.setattr(app.subprocess, "run", _timeout)

    resp = client.post("/parse?filename=doc.pdf", content=b"%PDF-1.4 fake")

    assert resp.status_code == 504
    assert resp.json()["error"] == "parse_timeout"


def test_parser_runs_in_a_child_process_with_timeout(monkeypatch, tmp_path):
    """Парсер вызывается ПОДПРОЦЕССОМ, и таймаут ему передан.

    Проверяется именно механика, а не результат: без дочернего процесса дедлайн
    невозможен в принципе — и ровно поэтому он годами не работал.
    """
    seen: dict = {}

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        seen["timeout"] = kw.get("timeout")
        (tmp_path / "md").mkdir(exist_ok=True)
        (tmp_path / "md" / "out.md").write_text("# ок", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(app.subprocess, "run", _fake_run)

    app.pdf_to_markdown(tmp_path / "in.pdf", tmp_path)

    assert seen["timeout"] == contracts.PARSE_TIMEOUT_SEC
    assert "opendataloader_pdf" in " ".join(str(c) for c in seen["cmd"])


def test_server_deadline_is_below_client_timeout():
    """Сумма серверных таймаутов < клиентского (`agents.opendataloader_timeout_sec`=180).

    Было 120 + 300 = 420: клиент уходил на 180-й секунде, а LibreOffice и JVM продолжали
    работать без потребителя. Уменьшение ничего не отнимает — документ, которому нужно
    больше 180 с, до вызывающего всё равно не доезжал.
    """
    total = contracts.LO_TIMEOUT_SEC + contracts.PARSE_TIMEOUT_SEC

    assert total < 180, (
        f"сумма серверных таймаутов {total}с не меньше клиентского 180с — "
        "сервер продолжит работу после ухода клиента"
    )
