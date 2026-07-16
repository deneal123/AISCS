# duckdb — сайдкар SQL-аналитики по файлам

Гоняет **SQL по загруженным табличным файлам** пользователя (CSV/Excel/Parquet/JSON) и отдаёт
результат. Нужен, чтобы ассистент считал точные агрегаты/фильтры/группировки **по реальным данным**,
а не по их усечённому текстовому превью. Ветка-сабмодуль репозитория GPTHub (как `whisper`,
`opendataloader`, `graphify`).

## Почему DuckDB, а не Velox/Axiom

[DuckDB](https://duckdb.org) — встраиваемый аналитический движок (MIT): один pip-пакет с движком
внутри, нативно читает `csv`/`tsv`/`parquet`/`json`, изолируется, не требует сервера БД. Тяжёлый
C++/Velox-движок (напр. facebookincubator/axiom) здесь оверкилл: у него нет HTTP-API (только CLI/либы),
сборка неподъёмная, а нам нужен тонкий сервис под файлы пользователя.

## Как устроено

- Свежий **in-memory** DuckDB-коннект на каждый запрос — изоляция между запросами.
- Файлы грузятся в **таблицы** (`csv`/`tsv`/`parquet`/`json` — нативными ридерами DuckDB;
  `xlsx` — через `openpyxl` → csv, дальше DuckDB выводит типы).
- После загрузки файлов в таблицы — `SET enable_external_access=false`: SQL от модели больше **не
  прочитает произвольный файл** (`read_csv('/etc/passwd')` → Permission Error).
- Пустой `sql` → возвращаем **схему + первые строки** каждой таблицы (разведочный вызов для модели).

> **Только встроенные ридеры.** Сайдкар живёт в `internal`-сети **без интернета**, поэтому
> DuckDB-расширения (`excel` и пр.) в рантайме не скачать — опираемся на встроенные. Сам сайдкар
> `xls`/`ods` не читает; бэкенд заранее конвертирует их в `xlsx` через сайдкар `opendataloader`
> (у него есть LibreOffice, эндпоинт `POST /convert`), и в DuckDB приходит уже `xlsx`.

## API

| Метод | Ответ |
|---|---|
| `GET /health` | `{"status": "ok", "formats": [...], "duckdb": "<версия>"}` |
| `GET /formats` | `{"formats": [".csv", ".parquet", ...]}` |
| `POST /query` | тело JSON (см. ниже) → результат SQL |

`POST /query` — тело:

```json
{
  "sql": "SELECT city, sum(sales) FROM t1 GROUP BY city",
  "files": [{ "name": "t1.csv", "content_b64": "<base64 файла>" }],
  "max_rows": 200
}
```

Ответ:

```json
{
  "columns": ["city", "sum(sales)"],
  "rows": [["Moscow", 180], ["Kazan", 50]],
  "row_count": 2,
  "truncated": false,
  "tables": [{ "name": "t1", "source": "t1.csv", "columns": [...], "row_count": 3 }],
  "duration_sec": 0.03,
  "sql": "…"
}
```

Пустой `sql` → в `tables[].preview` приходят первые строки. Ошибка SQL — это нормально: приходит
`{"error": "sql_error", "detail": "…"}` (модель исправляет запрос и вызывает снова).
Форматы: `csv`, `tsv`, `txt`, `parquet`, `pqt`, `json`, `jsonl`, `ndjson`, `xlsx`.

## Переменные окружения

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `PORT` | `8080` | Порт HTTP |
| `DUCKDB_MAX_ROWS` | `200` | Строк в ответе по умолчанию |
| `DUCKDB_HARD_MAX_ROWS` | `2000` | Жёсткий потолок строк |
| `DUCKDB_MEMORY_LIMIT` | `512MB` | Лимит памяти DuckDB на запрос (защита от OOM) |
| `DUCKDB_MAX_BODY_BYTES` | `67108864` | Потолок тела запроса (файлы приходят base64) |

## Как это видит бэкенд

Клиент — `DuckDBClient` + `gather_user_tabular_files`
(`backend/service/services/agents/domain/tools/duckdb_client.py`), инструмент агента `analyze_data`
(в `DEFAULT_FUNCTION_TOOLS` у general-агента). Включается флагом `AGENTS__DUCKDB_ENABLED`. Работает
**fail-open**: сайдкар недоступен / нет файлов → инструмент отвечает модели словами, а не роняет ход.
Табличные файлы пользователя берутся из объектного хранилища (MinIO) по метаданным `UserFile`.

## Локально

```bash
docker build -t duckdb-sidecar .
docker run --rm -p 8090:8080 duckdb-sidecar

B64=$(printf 'city,sales\nMoscow,100\nKazan,80\n' | base64 -w0)
curl -s -X POST http://localhost:8090/query -H 'Content-Type: application/json' \
  -d "{\"sql\":\"SELECT city, sum(sales) t FROM t1 GROUP BY city\",\"files\":[{\"name\":\"t1.csv\",\"content_b64\":\"$B64\"}]}" | jq
```
