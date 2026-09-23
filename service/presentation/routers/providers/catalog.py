"""`/catalog*` — каталог моделей.

Две РАЗНЫЕ вещи под одним префиксом:
  * `/catalog`             — метаданные моделей (окно контекста, возможности);
  * `/catalog/chat-models` — агрегированный список chat-совместимых id + их владельцы.

Цен нет ни там, ни там ПО ПОСТРОЕНИЮ: сырые цены провайдера раскрывали бы маржу
биллинга, поэтому наружу они не отдаются нигде.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.presentation.deps import internal_auth

router = APIRouter()


@router.get("/catalog")
async def catalog(authorization: str | None = Header(default=None)) -> dict:
    """Каталог моделей: окно контекста + возможности (зрение/аудио/файлы/tools).

    Провайдерами и их метаданными владеет САЙДКАР, а потребители backend'а (богатый
    пикер моделей, биллинг) берут каталог отсюда.
    """
    internal_auth(authorization)
    from service.shared.model_catalog import get_openrouter_catalog

    data = await get_openrouter_catalog()
    return {"count": len(data), "models": data}


@router.get("/catalog/chat-models")
async def chat_models(
    chat_only: bool = False, authorization: str | None = Header(default=None)
) -> dict:
    """Список ЧАТ-моделей + владелец-провайдер (``model_id → provider``).

    Биллингу нужен именно он: чтобы показать прайс по моделям, которые реально можно
    выбрать, и назвать реального владельца у id без префикса («gpt-5.5» → openai).

    ⚠️ ``chat_only`` не косметика: без него в списке есть ЭМБЕДДЕРЫ и прочие не-чат
    модели (замер: 422 против 335). Биллингу нужны все — эмбеддинги тоже тарифицируются;
    пикеру моделей — только чат-совместимые, иначе пользователь увидит в выборе
    ``Embeddings`` и выберет то, чем нельзя разговаривать.
    """
    internal_auth(authorization)
    try:
        from service.domain.client import build_qualified_model_catalog
        from service.domain.client.active import get_active_provider
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={"error": "engine_unavailable", "detail": "unavailable"},
        )
    models, owners = await build_qualified_model_catalog(get_active_provider())
    models = list(models or [])
    # The qualified catalog is already chat-only and evidence-backed.  Keep the
    # flag for wire compatibility; it must not reintroduce inventory-only IDs.
    return {"models": models, "owners": dict(owners or {})}


@router.get("/catalog/agents")
async def agents(authorization: str | None = Header(default=None)) -> dict:
    """Каталог агентов: `{имя: {label_ru, cost_class}}`.

    🔴 СПИСОК ОТДАЁТ ТОТ, КТО ИМ ВЛАДЕЕТ. Реестр агентов живёт здесь; вторая его копия у
    backend разошлась бы с этой молча, и «известен ли шаг» зависело бы от того, чей список
    свежее. Ровно тот же довод, что у каталога личностей рядом.

    ⚠️ Зачем backend: он принимает закрепление сценария из БРАУЗЕРА и обязан ответить
    честно. Сценарий с несуществующим шагом сайдкар при загрузке отбросит — а человек уже
    увидел бы «закреплено» и не понял, почему ничего не изменилось.
    """
    internal_auth(authorization)
    from service.domain.capabilities.runtime import get_static_catalog

    catalog = get_static_catalog()
    items = {
        name: {"label_ru": spec.label_ru, "cost_class": spec.cost_class}
        for name, spec in catalog.agents.items()
    }
    return {"count": len(items), "agents": items}


@router.get("/catalog/personas")
async def personas(authorization: str | None = Header(default=None)) -> dict:
    """Каталог ЛИЧНОСТЕЙ для селектора: `[{id, label}]`, только включённые.

    Реестром владеет сайдкар (у него схема и валидация), поэтому список отдаёт он же —
    иначе фронт показывал бы личности, которых валидация не пропустила, или прятал бы
    рабочие. Выключенные не отдаются вовсе: тёмная выкатка означает «личности нет для
    пользователя», а не «есть, но неактивна».
    """
    internal_auth(authorization)
    from service.domain.persona import catalog as persona_catalog

    items = persona_catalog()
    return {"count": len(items), "personas": items}
