"""HTTP-ручки сайдкара, сгруппированные по НАЗНАЧЕНИЮ.

Раньше всё лежало одним файлом на 580 строк вперемешку с загрузкой движка; затем —
плоским каталогом `api/` рядом с полупустым `presentation/`, где жил один-единственный
роутер `/v1`. Двух HTTP-слоёв в сервисе быть не должно: одинаковые вещи в разных местах
заставляют помнить, где что, вместо того чтобы это было видно.

Группировка по потребителю и по цене операции, а не по алфавиту:

    health.py       GET /health — хелсчек compose + контракт для сверки с backend
    agent/          ЯДРО: то, ради чего сервис существует
        run.py        POST /run   — прогон агента, NDJSON-стрим (зовёт воркер)
        route.py      POST /route — роутинг до диспатча (зовёт веб-процесс)
    providers/      ПРОВАЙДЕРЫ платформы — сайдкар единственный, кто им звонит
        keys.py       POST /providers/keys   — приём снимка ключей от backend
        health.py     GET  /providers/health — здоровье провайдеров (админка)
        catalog.py    GET  /catalog*         — модели для биллинга и пикера
    capabilities/   ВОЗМОЖНОСТИ движка, выставленные наружу как ручки
        tools.py      /tools/*  — веб-поиск, разбор ссылки, презентация
        media.py      /media/*  — провайдерские vision и STT
        vector.py     /vector/* — документы пользователя в Qdrant
    gateway/        ЧУЖОЙ протокол, живущий по чужим правилам
        openai_v1.py  /v1/*     — OpenAI-совместимый шлюз (memos, ldr, graphify, SDK)

⚠️ `gateway/` вынесен в отдельную группу не для красоты. Это единственное место, где
действуют не наши правила: своя форма ошибки (`{"error": {"message","type"}}`) и своя
проверка ключа, пускающая всех при пустом значении. Пока он лежал вперемешку с
остальными, эти правила расползались на соседей — так `/run` и `/providers/keys` и
оказались открытыми.

⚠️ Шлюза в `ALL_ROUTERS` НЕТ намеренно: он монтируется отдельно и только если загрузился
(см. `service/main.py`). Движка может не быть — сборка, отсутствующий маунт, — и сервис
всё равно обязан подняться с живым `/health`, где видно, почему шлюз недоступен.

`ALL_ROUTERS` — единственный список для сборки приложения. Роутер, не попавший сюда, для
сервиса не существует; перечислять их ещё и в `main.py` значило бы завести второе место,
где о нём надо помнить.
"""

from __future__ import annotations

from fastapi import APIRouter

from service.presentation.routers import health
from service.presentation.routers.agent import route, run
from service.presentation.routers.capabilities import (
    document_audit,
    media,
    tools,
    vector,
    workflow_catalog,
)
from service.presentation.routers.providers import catalog
from service.presentation.routers.providers import health as providers_health
from service.presentation.routers.providers import keys as provider_keys

# Порядок значения не имеет — префиксы не пересекаются. Перечислено в порядке групп из
# докстринга, чтобы список читался как оглавление каталога.
ALL_ROUTERS: tuple[APIRouter, ...] = (
    health.router,
    run.router,
    route.router,
    provider_keys.router,
    providers_health.router,
    catalog.router,
    tools.router,
    media.router,
    vector.router,
    workflow_catalog.router,
    document_audit.router,
)
