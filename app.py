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

import base64
import csv as csv_mod
import io
import json
import os
import re
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import duckdb
from openpyxl import load_workbook

PORT = int(os.environ.get("PORT", "8080"))
# Потолок тела запроса: файлы приходят base64 (≈+33%), поэтому лимит выше «сырого».
MAX_BODY_BYTES = int(os.environ.get("DUCKDB_MAX_BODY_BYTES", str(64 * 1024 * 1024)))
# Строк в ответе по умолчанию — чтобы не раздуть контекст LLM.
DEFAULT_MAX_ROWS = int(os.environ.get("DUCKDB_MAX_ROWS", "200"))
HARD_MAX_ROWS = int(os.environ.get("DUCKDB_HARD_MAX_ROWS", "2000"))
# Память DuckDB на запрос — защита от OOM на гигантском файле/джойне.
MEMORY_LIMIT = os.environ.get("DUCKDB_MEMORY_LIMIT", "512MB")
MAX_XLSX_ROWS = int(os.environ.get("DUCKDB_MAX_XLSX_ROWS", "100000"))

CSV_EXT = (".csv", ".tsv", ".txt")
NATIVE_EXT = (*CSV_EXT, ".parquet", ".pqt", ".json", ".jsonl", ".ndjson")
XLSX_EXT = (".xlsx",)
SUPPORTED_EXT = (*NATIVE_EXT, *XLSX_EXT)

_IDENT_RE = re.compile(r"[^0-9a-zA-Z_]+")


def ext_of(name: str) -> str:
    return Path(str(name or "")).suffix.lower()


def table_name_for(name: str, used: set[str]) -> str:
    """Имя файла → валидный SQL-идентификатор (уникальный в рамках запроса)."""
    stem = Path(str(name or "")).stem
    ident = _IDENT_RE.sub("_", stem).strip("_").lower() or "t"
    if ident[0].isdigit():
        ident = f"t_{ident}"
    base = ident
    i = 2
    while ident in used:
        ident = f"{base}_{i}"
        i += 1
    used.add(ident)
    return ident


def xlsx_to_csv_path(src: Path, workdir: Path) -> Path:
    """xlsx → csv (первый непустой лист) через openpyxl; типы выведет DuckDB."""
    wb = load_workbook(src, data_only=True, read_only=True)
    out = workdir / f"{src.stem}.csv"
    wrote = False
    for sheet in wb.worksheets:
        rows_iter = sheet.iter_rows(values_only=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv_mod.writer(fh)
            n = 0
            for row in rows_iter:
                if row is None or all(c is None for c in row):
                    continue
                writer.writerow(["" if c is None else c for c in row])
                n += 1
                wrote = wrote or n > 0
                if n >= MAX_XLSX_ROWS:
                    break
        if wrote:
            break  # берём первый лист с данными
    wb.close()
    if not wrote:
        raise ValueError("xlsx: нет данных ни на одном листе")
    return out


def load_file(con, name: str, raw: bytes, workdir: Path, used: set[str]) -> dict:
    """Записать файл в temp, создать из него таблицу DuckDB. → метаданные таблицы."""
    ext = ext_of(name)
    if ext not in SUPPORTED_EXT:
        raise ValueError(f"формат не поддержан: {ext or 'unknown'}")
    table = table_name_for(name, used)
    src = workdir / f"in_{table}{ext or '.dat'}"
    src.write_bytes(raw)

    q = f'"{table}"'
    if ext in CSV_EXT:
        delim = "\t" if ext == ".tsv" else ","
        con.execute(
            f"CREATE TABLE {q} AS SELECT * FROM read_csv_auto(?, delim=?, "
            f"header=true, sample_size=-1, all_varchar=false)",
            [str(src), delim],
        )
    elif ext in (".parquet", ".pqt"):
        con.execute(f"CREATE TABLE {q} AS SELECT * FROM read_parquet(?)", [str(src)])
    elif ext in (".json", ".jsonl", ".ndjson"):
        con.execute(f"CREATE TABLE {q} AS SELECT * FROM read_json_auto(?)", [str(src)])
    elif ext in XLSX_EXT:
        csv_path = xlsx_to_csv_path(src, workdir)
        con.execute(
            f"CREATE TABLE {q} AS SELECT * FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv_path)],
        )

    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? ORDER BY ordinal_position",
        [table],
    ).fetchall()
    row_count = con.execute(f"SELECT count(*) FROM {q}").fetchone()[0]
    return {
        "name": table,
        "source": name,
        "columns": [{"name": c[0], "type": c[1]} for c in cols],
        "row_count": int(row_count),
    }


def _jsonable(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def preview_tables(con, tables: list[dict], limit: int = 5) -> list[dict]:
    """Схема + первые строки каждой таблицы — для первого «разведочного» вызова."""
    out = []
    for t in tables:
        rows = con.execute(f'SELECT * FROM "{t["name"]}" LIMIT {int(limit)}').fetchall()
        out.append({**t, "preview": [[_jsonable(v) for v in r] for r in rows]})
    return out


def run_query(sql: str, files: list[dict], max_rows: int) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        con = duckdb.connect(database=":memory:")
        try:
            con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
        except Exception:
            pass
        try:
            used: set[str] = set()
            tables = [
                load_file(con, f.get("name") or "", base64.b64decode(f.get("content_b64") or ""), workdir, used)
                for f in files
            ]
            if not tables:
                raise ValueError("не передано ни одного файла")

            # После загрузки в таблицы отключаем внешний доступ: SQL от LLM больше не
            # сможет прочитать произвольный файл (read_csv('/etc/passwd') и т.п.).
            try:
                con.execute("SET enable_external_access=false")
            except Exception:
                pass

            sql = (sql or "").strip().rstrip(";")
            if not sql:
                # Разведка: отдаём схему + превью, чтобы модель написала SQL осознанно.
                return {
                    "sql": "",
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "truncated": False,
                    "tables": preview_tables(con, tables),
                    "duration_sec": round(time.monotonic() - started, 3),
                }

            cur = con.execute(sql)
            columns = [d[0] for d in (cur.description or [])]
            cap = max(1, min(int(max_rows or DEFAULT_MAX_ROWS), HARD_MAX_ROWS))
            rows = cur.fetchmany(cap + 1)
            truncated = len(rows) > cap
            rows = rows[:cap]
            return {
                "sql": sql,
                "columns": columns,
                "rows": [[_jsonable(v) for v in r] for r in rows],
                "row_count": len(rows),
                "truncated": truncated,
                "tables": [{k: t[k] for k in ("name", "source", "columns", "row_count")} for t in tables],
                "duration_sec": round(time.monotonic() - started, 3),
            }
        finally:
            con.close()


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
            return self._json(200, {"status": "ok", "formats": list(SUPPORTED_EXT), "duckdb": duckdb.__version__})
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
