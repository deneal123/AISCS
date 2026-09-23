# Сайдкар агентного движка GPTHub: FastAPI-сервис, исполняющий агентский пайплайн в
# ДОЛГОЖИВУЩЕМ процессе (в отличие от celery loop-per-task в backend).
#
# Здесь описывалась «оболочка: пока /health, движок приедет в Фазах 3-4» — переезд
# давно завершён, образ несёт весь движок и отдаёт 18 ручек.
FROM python:3.13-slim

# curl — для healthcheck compose (как у duckdb/opendataloader/graphify).
# libzbar0 — системная половина `pyzbar`: чтение QR и штрихкодов с картинок. Без неё
# пакет ставится, но импорт падает, и декодер молча выключается (fail-open) — то есть
# QR снова начнёт УГАДЫВАТЬ зрячая модель. ~150 КБ, отдельного сайдкара не стоит.
RUN apt-get update && apt-get install -y --no-install-recommends curl libzbar0 \
    && rm -rf /var/lib/apt/lists/*

# Зависимости — из pyproject + ЛОКА, а не строками pip install. Раньше список жил
# в трёх местах (Dockerfile, CI, головы) и синхронизировался вручную по комментарию
# «версии синхронны с backend» — то есть ничем. Лок делает образ воспроизводимым:
# та же сборка через месяц даст те же версии.
#
# Слой зависимостей отдельно от кода: правка кода не пересобирает установку.
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock /opt/agents-sidecar/
WORKDIR /opt/agents-sidecar
RUN uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY docker/entrypoint.sh /opt/agents-sidecar/entrypoint.sh
RUN chmod +x /opt/agents-sidecar/entrypoint.sh

# Движок — СВОЙ КОД сайдкара, а не чужой: копируется в образ, а не монтируется из
# backend. До этого сервис владел двумя файлами и монтировал 101 из соседнего репозитория,
# то есть не собирался и не деплоился отдельно — микросервисом он не был.
#
# Пакет зовётся `service` — как у backend. В ОБРАЗЕ коллизии нет: сервисы
# живут в разных контейнерах, а кросс-сервисные тесты, которые грузили оба
# пакета в один интерпретатор, переехали сюда и backend больше не импортят.
# Раньше пакет лежал по пути `service/services/agents` — слепок монолита, из которого
# он выехал: в репозитории, который ЦЕЛИКОМ и есть сервис агентов, это читалось как
# «сервис → сервисы → агенты» и маскировало чужие импорты `service.*` под свои.
# Весь код сервиса — ОДНИМ каталогом, как `service/` у backend. Раньше он лежал
# тремя кусками в корне (app.py, api/, gpthub_agents/), и три COPY надо было не
# забыть синхронно — ровно так у тонких сайдкаров и потерялся core.py.
COPY service /opt/agents-sidecar/service

# Fail the image build on the same source-controlled capability defect that would
# otherwise stop the ASGI lifespan. Release tooling validates the safe manifest.
RUN python -m service.presentation.cli.capability_manifest > /dev/null

# PYTHONPATH — чтобы `import gpthub_agents...` работал одинаково
# независимо от способа запуска (uvicorn, pytest, python -c).
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/agents-sidecar \
    PORT=8090
EXPOSE 8090
ENTRYPOINT ["/opt/agents-sidecar/entrypoint.sh"]
