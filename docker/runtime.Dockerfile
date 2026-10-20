# Образ РАНТАЙМА песочницы — то, внутри чего исполняется код агента. Это НЕ образ
# сайдкара (он в соседнем `Dockerfile`): сайдкар управляет контейнерами, а этот образ и
# есть управляемый контейнер.
#
# 🔴 ЗАЧЕМ ОТДЕЛЬНЫЙ ОБРАЗ, А НЕ ГОЛЫЙ `python:3.12-slim`. Истории версий песочницы
# (`ws_log`/`ws_diff`/`ws_revert`) нужен `git`, а в slim его нет. Доставить его в рантайме
# нельзя: у песочницы `network: none` и корень только для чтения — и это правильно.
# Значит бинарь обязан приехать в образе.
#
# ⚠️ Ставим МИНИМУМ. Каждый лишний пакет здесь — это поверхность, доступная коду, который
# пишет модель по просьбе постороннего человека.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Каталог работы. Права — на «никого» (`65534`), под которым сайдкар и запускает процесс:
# созданный root-ом каталог был бы для него нечитаем, и песочница отказывала бы на первой
# же записи.
RUN mkdir -p /workspace && chown 65534:65534 /workspace

# ⚠️ Владельца каталога `.git` git проверяет отдельно (`safe.directory`): смонтированный
# том принадлежит другому uid, и без этой строки любая git-команда отвечает «dubious
# ownership» — то есть история молча не ведётся.
RUN git config --system --add safe.directory '*'

WORKDIR /workspace

# Root-owned control plane; project files and /tmp cannot replace the supervisor.
COPY docker/harness /opt/gpthub-harness
RUN chmod -R a-w /opt/gpthub-harness
