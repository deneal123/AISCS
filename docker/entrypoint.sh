#!/bin/sh
set -e

# 🔴 Падаем НА СТАРТЕ, а не на первом запросе. Оба ключа обязательны: без ключа сервиса
# ручка с docker.sock открыта всем, кто дотянулся до внутренней сети, а без секрета
# подписи токен владения подделывается — то есть чужая песочница доступна по идентификатору.
[ -n "$WORKSPACE_API_KEY" ] || { echo "WORKSPACE_API_KEY не задан"; exit 1; }
[ -n "$WORKSPACE_OWNER_SECRET" ] || { echo "WORKSPACE_OWNER_SECRET не задан"; exit 1; }

# Проверяем рантайм: без доступа к демону сервис бесполезен, и знать это надо сразу.
docker version --format '{{.Server.Version}}' >/dev/null 2>&1 \
  || { echo "docker.sock недоступен — песочницы создавать нечем"; exit 1; }

python3 -c "import fastapi, uvicorn; print('fastapi', fastapi.__version__)"

exec python3 /opt/workspace-sidecar/service/app.py
