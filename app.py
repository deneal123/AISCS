#!/usr/bin/env python3
"""Тонкая HTTP-обёртка: SQL/аналитика по загруженным табличным файлам через DuckDB.

Без веб-фреймворка (stdlib http.server + duckdb + openpyxl). На каждый запрос —
свежее in-memory DuckDB-соединение (изоляция между запросами), файлы грузятся в
ТАБЛИЦЫ, затем внешний доступ к ФС отключается — SQL от LLM видит только таблицы.

  POST /query   body(JSON) = {
      "sql": "<опц. SQL; пусто → схема+превью таблиц>",
      "files": [{"name": "sales.csv", "content_b64": "<base64>"}, ...],
      "max_rows": 200
    }
    → {"columns": [...], "rows": [[...]], "row_count": N, "truncated": bool,
       "tables": [{"name","columns":[{name,type}],"row_count"}],
       "duration_sec": <float>, "sql": "<исполненный или ''>"}
  GET /health   → {"status":"ok","formats":[...],"duckdb": "<версия>"}
  GET /formats  → {"formats":[...]}

Почему DuckDB, а не тяжёлый Velox/Axiom: один pip-пакет, нативно читает
csv/tsv/parquet/json, встраивается, изолируется. xlsx читаем через openpyxl →
csv (DuckDB сам выведет типы) — расширение `excel` тянуть по сети нельзя: сайдкар
на internal-сети без интернета.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import duckdb

# Логика — в core.py; здесь только транспорт.
from core import (
    DEFAULT_MAX_ROWS,
    MAX_BODY_BYTES,
    SUPPORTED_EXT,
    run_query,
)

PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/health":
            return self._json(
                200, {"status": "ok", "formats": list(SUPPORTED_EXT), "duckdb": duckdb.__version__}
            )
        if self.path.split("?", 1)[0] == "/formats":
            return self._json(200, {"formats": list(SUPPORTED_EXT)})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/query":
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return self._json(400, {"error": "empty body"})
        if length > MAX_BODY_BYTES:
            return self._json(413, {"error": "request too large"})
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return self._json(400, {"error": "invalid JSON body"})

        files = payload.get("files") or []
        if not isinstance(files, list) or not files:
            return self._json(400, {"error": "no files provided"})
        sql = payload.get("sql") or ""
        max_rows = payload.get("max_rows") or DEFAULT_MAX_ROWS

        try:
            return self._json(200, run_query(sql, files, max_rows))
        except duckdb.Error as exc:
            # Ошибка SQL — это НОРМАЛЬНО: возвращаем модели текст, пусть исправит запрос.
            return self._json(200, {"error": "sql_error", "detail": str(exc)[-600:], "sql": sql})
        except Exception as exc:  # defensive: любой сбой → нет результата
            return self._json(500, {"error": "query failed", "detail": str(exc)[-400:]})

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    print(
        f"duckdb-sidecar on :{PORT} | duckdb={duckdb.__version__} "
        f"| formats={len(SUPPORTED_EXT)} | max_rows={DEFAULT_MAX_ROWS}",
        flush=True,
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
