#!/bin/sh
set -e

# Проверяем рантайм на старте: падать здесь лучше, чем 500 на первом запросе.
# Контракт провода — то, чем сайдкар говорит с backend. Если модуль не подан
# (сломанный маунт/COPY), падаем ЗДЕСЬ с внятной ошибкой, а не туманным
# ImportError при первом запросе. Проверка намеренно ЖЁСТКАЯ: сервис без контракта
# не сервис, и /health, отдающий 200 в этом состоянии, вводил бы в заблуждение.
python3 -c "import fastapi, uvicorn; print('fastapi', fastapi.__version__, '| uvicorn', uvicorn.__version__)"
python3 -c 'from service.events import EventType; from service.schemas.run import AgentRunInput; print("contract OK:", len(list(EventType)), "event types,", len(AgentRunInput.model_fields), "run fields")'

exec python3 -m service.main
