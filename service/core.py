"""Логика сайдкара duckdb: загрузка файлов в таблицы и исполнение SQL.

Шов между транспортом и логикой ровно один: `app.py` держит HTTP, `core.py` —
то, что проверяется тестом. Здесь же живут два гарда, которые ломаются тихо:

  * `table_name_for` — имя ФАЙЛА пользователя превращается в SQL-идентификатор и
    подставляется в запрос f-строкой (`preview_tables`, `load_file`). Без
    санитизации это инъекция через имя файла.
  * `SET enable_external_access=false` в `run_query` — единственное, что стоит
    между SQL, написанным моделью, и файловой системой контейнера. Стоит внутри
    `try/except: pass`, поэтому переименование настройки в DuckDB убрало бы
    песочницу молча.
"""

import base64
import csv as csv_mod
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import duckdb

# ⚠️ Границы контракта импортируются, а не объявляются здесь заново. `MAX_BODY_BYTES`
# раньше жил в этом файле, а `PORT` был объявлен ДВАЖДЫ — тут и в `app.py`, с
# независимым чтением одной и той же переменной окружения. Источник правды один:
# `contracts.py` (только stdlib, поэтому его может загрузить страж без duckdb).
from contracts import MAX_BODY_BYTES, QUERY_TIMEOUT_SEC  # noqa: F401 — ре-экспорт для app.py
from openpyxl import load_workbook

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

# 🔴 БУКВЫ ЛЮБОГО АЛФАВИТА, а не только латиница. Здесь стояло `[^0-9a-zA-Z_]+`, и всякое
# кириллическое имя вырождалось целиком: «отчёт за май.csv» → пусто → служебное `t`. У
# русскоязычного продукта такие имена — норма, то есть ПОЧТИ ВСЕ таблицы звались `t`, `t_2`,
# `t_3`, и модель, спрошенная «сколько в отчёте за май», не могла понять, какая из них какая.
# DuckDB кириллицу в идентификаторах принимает БЕЗ КАВЫЧЕК — проверено на живом сайдкаре.
_IDENT_RE = re.compile(r"[^\w]+", re.UNICODE)


def ext_of(name: str) -> str:
    return Path(str(name or "")).suffix.lower()


def table_name_for(name: str, used: set[str]) -> str:
    """Имя файла → валидный SQL-идентификатор (уникальный в рамках запроса).

    ⚠️ Имя таблицы — то, чем модель обращается к данным в SQL, поэтому оно обязано быть
    УЗНАВАЕМЫМ. Замер: файл `iris.csv` уезжал в сайдкар под именем `t1.csv`, модель видела в
    промпте настоящее имя вложения и писала `FROM iris` → «Table with name iris does not
    exist», четыре вызова впустую и ответ «произошла ошибка доступа к файлу».
    """
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


class UnsupportedFormat(ValueError):
    """Расширение файла не поддерживается.

    Отдельный тип, а не голый `ValueError`: транспорт обязан отличать «клиент прислал
    не тот файл» (415) от «у нас сломалось» (500). Раньше здесь был `ValueError`, он
    проваливался в общий `except Exception` и превращался в 500 «query failed» — то
    есть вина сваливалась на сервис, а вызывающий не мог понять, что чинить.
    """


def load_file(con, name: str, raw: bytes, workdir: Path, used: set[str]) -> dict:
    """Записать файл в temp, создать из него таблицу DuckDB. → метаданные таблицы."""
    ext = ext_of(name)
    if ext not in SUPPORTED_EXT:
        raise UnsupportedFormat(f"формат не поддержан: {ext or 'unknown'}")
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


def _seal_external_access(con) -> None:
    """Закрыть DuckDB доступ к файловой системе и сети — и УБЕДИТЬСЯ, что закрыт.

    ⚠️ Раньше здесь стояло `try: SET … except: pass`. Это ровно тот случай, когда
    «на всякий случай не падать» отключает защиту: переименуй DuckDB настройку в
    новой версии — `SET` бросит, `pass` проглотит, и SQL от модели пойдёт
    выполняться по НЕЗАПЕЧАТАННОМУ соединению. Тихо, без единой строчки в логах.

    Поэтому: во-первых, отказ поднимается наверх; во-вторых, факт закрытия
    ПРОВЕРЯЕТСЯ чтением значения, а не верой в то, что `SET` подействовал. Второе
    важнее первого — оно ловит и молчаливое игнорирование неизвестной настройки.
    """
    try:
        con.execute("SET enable_external_access=false")
        applied = con.execute("SELECT current_setting('enable_external_access')").fetchone()
    except Exception as exc:  # настройка исчезла/переименована — это не «мелочь»
        raise RuntimeError(
            "DuckDB: не удалось закрыть внешний доступ (enable_external_access). "
            "Выполнять SQL от модели с открытой ФС нельзя — прогон остановлен."
        ) from exc
    if applied and applied[0] not in (False, 0, "false", "0"):
        raise RuntimeError(
            f"DuckDB: внешний доступ остался открыт (enable_external_access={applied[0]!r})."
        )


class QueryTimeout(Exception):
    """Работа не уложилась в серверный дедлайн и была прервана.

    Отдельный тип нужен, чтобы отличить таймаут от ошибки SQL. Иначе не выйдет:
    `duckdb.InterruptException` — ПОДКЛАСС `duckdb.Error`, то есть обработчик ошибок
    запроса поймал бы прерывание первым и отдал модели «поправь SQL» с кодом 200.
    Модель бы послушно переписала корректный запрос, а он снова упёрся бы в дедлайн.
    """


def run_query(sql: str, files: list[dict], max_rows: int) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        con = duckdb.connect(database=":memory:")
        try:
            con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
        except Exception:
            pass
        # ⚠️ СЕРВЕРНЫЙ ДЕДЛАЙН. До него таймаута на стороне сайдкара не было ВООБЩЕ:
        # клиент отваливался по своим 60 с, а `con.execute` продолжал считать запрос,
        # написанный моделью, — процессорное время горело без единого потребителя.
        #
        # Дедлайн накрывает и ЗАГРУЗКУ файлов, а не только SQL: распарсить присланный
        # csv на десятки миллионов строк ничуть не быстрее тяжёлого join'а.
        #
        # ⚠️ ПОЧЕМУ СТОРОЖ В ЦИКЛЕ, А НЕ ОДИН `threading.Timer`. `interrupt()` гасит
        # ТОЛЬКО ИДУЩИЙ запрос; сработав в промежутке между двумя (например, между
        # загрузкой последнего файла и стартом SQL), он пропадает впустую — и дедлайн
        # молча не применяется. Тест это и поймал: запрос отработал целиком.
        # Поэтому сторож бьёт повторно, пока работа не кончится.
        done = threading.Event()

        def _watchdog() -> None:
            if done.wait(QUERY_TIMEOUT_SEC):
                return  # уложились — прерывать нечего
            while not done.wait(0.2):
                con.interrupt()

        watchdog = threading.Thread(target=_watchdog, daemon=True, name="duckdb-deadline")
        watchdog.start()
        try:
            used: set[str] = set()
            tables = [
                load_file(
                    con,
                    f.get("name") or "",
                    base64.b64decode(f.get("content_b64") or ""),
                    workdir,
                    used,
                )
                for f in files
            ]
            if not tables:
                raise ValueError("не передано ни одного файла")

            # После загрузки в таблицы закрываем внешний доступ: SQL от LLM больше не
            # сможет прочитать произвольный файл (read_csv('/etc/passwd') и т.п.).
            _seal_external_access(con)

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
                "tables": [
                    {k: t[k] for k in ("name", "source", "columns", "row_count")} for t in tables
                ],
                "duration_sec": round(time.monotonic() - started, 3),
            }
        except duckdb.InterruptException as exc:
            # Прерывание пришло от нашего же сторожа — это дедлайн, а не кривой SQL.
            # Без этого преобразования InterruptException (подкласс `duckdb.Error`)
            # приехал бы в транспорте в ветку sql_error и вернулся с кодом 200.
            raise QueryTimeout(f"дедлайн {QUERY_TIMEOUT_SEC:g}с исчерпан") from exc
        finally:
            # Сначала гасим сторожа, потом закрываем соединение: иначе он может
            # дёрнуть `interrupt()` по уже закрытому соединению.
            done.set()
            watchdog.join(timeout=1.0)
            con.close()
