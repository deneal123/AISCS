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
#
# 🔴 Пакет называется `docker-cli`, НЕ `docker.io`. В Debian 13 клиент вынесли в отдельный
# пакет, и `docker.io` ставит ТОЛЬКО рантайм: образ собирался успешно, `dpkg -l` показывал
# docker, а `/usr/bin/docker` не существовал. Нашёл живой запуск — тесты увидеть этого не
# могли по построению, они подменяют драйвер.
#
# ⚠️ `docker --version` в том же слое: сборка обязана падать здесь, а не контейнер — на
# старте. Проверка стоит секунду и закрывает весь класс «пакет переименовали».
RUN apt-get update && apt-get install -y --no-install-recommends curl docker-cli \
    && rm -rf /var/lib/apt/lists/* \
    && docker --version

ARG FASTAPI_VERSION=0.115.6
ARG UVICORN_VERSION=0.34.0
ARG HTTPX_VERSION=0.28.1
# ⚠️ Версии обязаны совпадать с dev-зависимостями в pyproject.toml: тесты идут на той же
# версии транспорта, что исполняет прод.
# 🔴 `httpx` — РАНТАЙМ-зависимость (импорт качает файл по ссылке), а не только тестовая.
# Её отсутствия тесты увидеть не могли: у них она есть из dev-набора, а сервис в проде
# падал ModuleNotFoundError на старте.
RUN pip install --no-cache-dir \
        "fastapi==${FASTAPI_VERSION}" \
        "uvicorn==${UVICORN_VERSION}" \
        "httpx==${HTTPX_VERSION}"

COPY service /opt/workspace-sidecar/service
COPY docker/entrypoint.sh /opt/workspace-sidecar/entrypoint.sh
RUN chmod +x /opt/workspace-sidecar/entrypoint.sh

# 🔴 СБОРКА ОБЯЗАНА ПАДАТЬ НА НЕДОСТАЮЩЕЙ ЗАВИСИМОСТИ, а не контейнер на старте. Импорт
# приложения целиком поднимает каждый модуль сервиса — то есть закрывает весь класс
# «в образе нет пакета, который код импортирует». Оба таких дефекта за день ловил ЗАПУСК,
# и оба тесты увидеть не могли: у них зависимости из dev-набора.
RUN PYTHONPATH=/opt/workspace-sidecar/service python3 -c "import app; print('импорт сервиса ок')"

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
