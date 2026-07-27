# Сайдкар workspace: файловая песочница для агента.
#
# 🔴 ЕДИНСТВЕННЫЙ СЕРВИС, КОТОРОМУ ОТДАН `docker.sock`. Именно поэтому он отдельный: слой
# `agents` исполняет управляемый моделью поток для ВСЕХ арендаторов одним процессом, и
# доступ к демону оттуда означал бы root на хосте из кода, который пишет модель.
#
# Сам сервис не считает ничего: он управляет чужим рантаймом. Отсюда и зависимости — только
# транспорт плюс клиент docker.
FROM python:3.12-slim

# curl — healthcheck compose; docker-cli — единственный способ, которым сервис работает.
# ⚠️ Ставим КЛИЕНТ, а не демон: демон здесь не нужен и был бы docker-in-docker, то есть
# ещё одна привилегированная поверхность.
RUN apt-get update && apt-get install -y --no-install-recommends curl docker.io \
    && rm -rf /var/lib/apt/lists/*

ARG FASTAPI_VERSION=0.115.6
ARG UVICORN_VERSION=0.34.0
# ⚠️ Версии обязаны совпадать с dev-зависимостями в pyproject.toml: тесты идут на той же
# версии транспорта, что исполняет прод.
RUN pip install --no-cache-dir \
        "fastapi==${FASTAPI_VERSION}" \
        "uvicorn==${UVICORN_VERSION}"

COPY service /opt/workspace-sidecar/service
COPY docker/entrypoint.sh /opt/workspace-sidecar/entrypoint.sh
RUN chmod +x /opt/workspace-sidecar/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/workspace-sidecar/service \
    HOME=/tmp \
    WORKSPACE_DRIVER=docker \
    WORKSPACE_TTL_SEC=1800 \
    WORKSPACE_EXEC_TIMEOUT_SEC=120 \
    WORKSPACE_MAX_WORKSPACES=32 \
    PORT=8080
EXPOSE 8080
ENTRYPOINT ["/opt/workspace-sidecar/entrypoint.sh"]
