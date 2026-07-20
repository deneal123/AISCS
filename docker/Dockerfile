# Сайдкар аналитики: SQL по загруженным табличным файлам через DuckDB.
#
# DuckDB — встраиваемый аналитический движок (MIT), один pip-пакет с движком
# внутри: нативно читает csv/tsv/parquet/json, изолируется, не требует сервера БД.
# Живёт отдельным контейнером (как whisper/opendataloader), чтобы не тащить движок
# и его память в backend/celery-воркеры и не считать тяжёлые джойны в API-процессе.
#
# ВАЖНО: сайдкар на internal-сети БЕЗ интернета — DuckDB-расширения (excel и пр.)
# в рантайме не скачать. Поэтому опираемся только на встроенные ридеры
# (csv/parquet/json), а xlsx читаем через openpyxl → csv (см. app.py).
FROM python:3.12-slim

# curl — для healthcheck compose (как у opendataloader/graphify).
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ARG DUCKDB_VERSION=1.3.2
ARG OPENPYXL_VERSION=3.1.5
RUN pip install --no-cache-dir \
        "duckdb==${DUCKDB_VERSION}" \
        "openpyxl==${OPENPYXL_VERSION}"

# ⚠️ core.py ОБЯЗАТЕЛЕН: логика вынесена туда из app.py, и без него контейнер
# падает на импорте. Проверяется тем, что образ действительно собирается и
# отвечает на /health — иначе такой промах виден только в проде.
# Код — каталогом `service/`, как у backend.
COPY service /opt/duckdb-sidecar/service
COPY docker/entrypoint.sh /opt/duckdb-sidecar/entrypoint.sh
RUN chmod +x /opt/duckdb-sidecar/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DUCKDB_MAX_ROWS=200 \
    DUCKDB_HARD_MAX_ROWS=2000 \
    DUCKDB_MEMORY_LIMIT=512MB \
    DUCKDB_MAX_BODY_BYTES=67108864 \
    PORT=8080
EXPOSE 8080
ENTRYPOINT ["/opt/duckdb-sidecar/entrypoint.sh"]
