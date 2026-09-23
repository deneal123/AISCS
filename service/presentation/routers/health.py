"""`GET /health` — хелсчек compose и главное окно диагностики сервиса.

Здесь же публикуется КОНТРАКТ, по которому backend сверяется тестом паритета: два
сервиса пинят `gpthub-core` независимо, и разошедшийся контракт `/run` — это молча
испорченный денежный путь (воркер биллит из result-dict).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from service.contracts import (
    BILLABLE_TOOLS,
    ERROR_CODES,
    MAX_BODY_BYTES,
    RESULT_FIELDS,
    ROUTE_RESPONSE_FIELDS,
)
from service.events import EventType
from service.presentation import runtime
from service.presentation.routers.providers import keys as provider_keys
from service.schemas.run import AMBIENT_FIELDS, AgentRunInput
from service.shared.agent_settings import describe_settings
from service.shared.provider_policy_context import describe as describe_policy

router = APIRouter()


def _contract() -> dict:
    """Имена, по которым потребитель сверяет свою копию провода.

    Именно ИМЕНА, а не счётчики: «20 полей» совпадёт и при разных наборах, а
    разъехавшийся контракт `/run` — это молча испорченный денежный путь.
    """
    return {
        "event_types": sorted(e.value for e in EventType),
        "run_input_fields": sorted(AgentRunInput.model_fields),
        "ambient_fields": sorted(AMBIENT_FIELDS),
        # ВЫХОД, а не только вход: воркер списывает деньги из ОТВЕТА — result-dict
        # `/run` и `routing_usage` из `/route`. Читает через `.get(...) or 0`,
        # поэтому разъехавшееся имя не падает, а тихо даёт ноль.
        "result_fields": sorted(RESULT_FIELDS),
        "route_response_fields": sorted(ROUTE_RESPONSE_FIELDS),
        # Коды ошибок и биллингуемые инструменты — тоже часть провода: по первым
        # вызывающий различает случаи, по вторым backend ищет надбавку. Публикуем,
        # чтобы расхождение было видно снаружи, а не только в тестах.
        "error_codes": sorted(ERROR_CODES),
        "billable_tools": sorted(BILLABLE_TOOLS),
        # Потолок тела — тоже часть провода: вызывающий по нему решает, резать ли
        # контекст У СЕБЯ. У остальных сайдкаров он публикуется здесь же.
        "max_body_bytes": MAX_BODY_BYTES,
    }


@router.get("/health")
async def health(request: Request) -> dict:
    """Хелсчек compose + окно диагностики: что живо и на каком контракте говорим."""
    from service.domain.capabilities.runtime import get_static_catalog
    from service.domain.documents.runtime_digest import (
        DOCUMENT_RUNTIME_DIGEST,
        DOCUMENT_RUNTIME_VERSION,
    )

    capability_catalog = get_static_catalog()
    return {
        "status": "ok",
        "service": "agents",
        "version": request.app.version,
        "capabilities": {
            "status": "ok",
            "capability_version": capability_catalog.version,
            "capability_digest": capability_catalog.digest,
            "agent_count": len(capability_catalog.agents),
            "workflow_count": len(capability_catalog.workflows),
            "native_tool_count": len(capability_catalog.native_tools),
        },
        "document_runtime": {
            "version": DOCUMENT_RUNTIME_VERSION,
            "digest": DOCUMENT_RUNTIME_DIGEST,
            "status": "ok",
        },
        # Имена полей контракта: по ним backend сверяет, что говорит с сайдкаром на
        # одном языке.
        #
        # Дубль под старым именем `gpthub_core` снят. Отсрочка «на один релиз»
        # писалась на случай, когда новый backend встречает старый сайдкар, — но такой
        # топологии здесь нет: оба сервиса выкладываются из ОДНОГО коммита
        # суперпроекта, прод-compose собирает сайдкар из закреплённого гитлинка.
        # Окна рассинхронизации не существует, а `contract` публикуется с прошлого
        # релиза, так что и при накатывании по одному потребитель читает его.
        "contract": _contract(),
        # Готовность ДВИЖКА. Нет — /run отдаст 503 с этой же причиной, а healthcheck
        # останется зелёным: контейнер надо диагностировать, а не ловить рестарт-петлю.
        "engine": {
            "available": runtime.DefaultAgentExecutionService is not None,
            "error": runtime.ENGINE_ERROR,
        },
        # Готовность LLM-шлюза /v1 (его зовут memos/ldr/graphify).
        "gateway_v1": {"available": runtime.v1_router is not None, "error": runtime.GATEWAY_ERROR},
        # Роутинг — отдельной строкой: он однажды отвалился молча (модуль не переехал
        # вместе с движком), а backend это проглатывал и слал сообщения без роутинга.
        "routing": {
            "available": runtime.ModelRoutingService is not None,
            "error": runtime.ROUTING_ERROR,
        },
        # Провайдерная политика приезжает снимком в /run и запоминается на процесс.
        # `known: false` = ни одного прогона ещё не было, и пути без своего снимка
        # (в первую очередь /v1) считают, что запрещённых провайдеров нет.
        "provider_policy": describe_policy(),
        # Админ-настройки агентов: `known: false` = ни одного прогона не было, движок
        # читает дефолты конфига (тумблеры из админки в этот момент не действуют).
        "agent_settings": describe_settings(),
        # Версия применённых провайдерских ключей — по ней backend понимает, что снимок
        # надо запушить заново (например, сайдкар перезапустился). ТОЛЬКО версия и имена:
        # значения ключей наружу не отдаются никогда.
        "provider_keys": {"version": provider_keys.KEYS_VERSION},
    }
