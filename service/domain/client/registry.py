"""Реестр LLM-провайдеров: порядок выбора и подбор модели под провайдера.

Используется фасадом ([client/__init__.py]) для ретраев и фейловера. Все модули
провайдеров имеют одинаковый интерфейс (см. mws_client) и кэш моделей.
"""

from __future__ import annotations

import asyncio
import logging

from service.settings import config
from service.shared.agent_settings import runtime_settings
from service.shared.model_class import is_not_pricier_than

from .model_catalog import ModelCatalogSource, ModelCatalogStatus, ProviderModelCatalog
from .model_qualification import (
    qualify_catalog,
)
from .model_requirements import (
    ModelQualification,
    ModelRequirement,
)
from .provider_admission import RunProviderAdmission
from .providers import gigachat, mws, openai, openrouter, routerai

logger = logging.getLogger(__name__)

# Модули провайдеров. Единственное место, где новый провайдер добавляется в систему:
# имя берётся из его собственной спеки, а не пишется здесь второй раз.
_PROVIDER_SOURCES = (
    mws,
    openai,
    openrouter,
    gigachat,
    routerai,
)


def _discover() -> dict:
    """Имя провайдера → модуль. Имя даёт САМ модуль (`PROVIDER_NAME`).

    ⚠️ Здесь был словарь-литерал, где имя писалось РЯДОМ с модулем. Опечатка в ключе
    давала провайдера, который не резолвится по своему настоящему имени: реестр знает
    его как «openrouetr», настройки и трейс — как «openrouter», и не сходится ничего,
    причём молча.
    """
    discovered: dict = {}
    for module in _PROVIDER_SOURCES:
        name = str(getattr(module, "PROVIDER_NAME", "") or "").strip().lower()
        if not name:
            logger.error("Провайдер-модуль %s не объявил PROVIDER_NAME — пропущен", module)
            continue
        discovered[name] = module
    return discovered


# Имя провайдера → модуль-обёртка.
PROVIDER_MODULES = _discover()


async def drain_provider_generations() -> None:
    """Close retired provider clients without exposing connection details."""

    await asyncio.gather(
        *(
            runtime.drain_generations()
            for module in PROVIDER_MODULES.values()
            if (runtime := getattr(module, "_RUNTIME", None)) is not None
            and hasattr(runtime, "drain_generations")
        ),
        return_exceptions=True,
    )


# Модели, неспособные к текстовому chat/completions: покажи такую в каталоге — и юзер
# выберет модель, которую мы не умеем биллить как чат, а провайдеру платим. Эмбеддинги
# вызываются по явному id. «vision»/«search» НЕ блокируем — обычные чат-модели.
_BLOCKED_MODEL_MARKERS = (
    # эмбеддинги / реранкеры
    "bge",
    "e5",
    "gte",
    "embed",
    "embedding",
    "rerank",
    "ranker",
    # аудио / речь / realtime
    "whisper",
    "asr",
    "stt",
    "tts",
    "speech",
    "transcribe",
    "audio",
    "realtime",
    # изображения / видео / музыка (генеративные бренды без чат-вариантов)
    "image",
    "dall-e",
    "dalle",
    "imagen",
    "sora",
    "veo",
    "video",
    "flux",
    "lyria",
    "midjourney",
    "stable-diffusion",
    "sdxl",
    "ideogram",
    "recraft",
    "kolors",
    "seedream",
    "seedance",
    "kling",
    # модерация / гардрейлы
    "moderation",
    "guard",
)


def is_chat_capable(model: str) -> bool:
    """Модель пригодна для текстового чата (не эмбеддер/аудио/картинки/модерация).

    Используется для ФИЛЬТРА ВЫБОРА чат-модели (не для каталога биллинга — там нужны
    все модели, за которые мы платим провайдеру)."""
    low = (model or "").lower()
    return bool(low) and not any(marker in low for marker in _BLOCKED_MODEL_MARKERS)


def get_provider_module(name: str):
    return PROVIDER_MODULES.get((name or "").strip().lower())


def get_spec(name: str):
    """Декларация провайдера или None. Единая точка чтения его свойств.

    ⚠️ Через неё теперь отвечают на вопросы «понимает ли include_usage», «какой у него
    диалект function-calling» и т.п. Раньше каждый такой вопрос имел собственное
    множество имён в своём модуле, и провайдер, забытый в одном из них, деградировал
    молча: терял точный учёт токенов или получал 422 на инструментах.
    """
    module = get_provider_module(name)
    return getattr(module, "SPEC", None) if module is not None else None


def all_specs() -> dict:
    """Все известные спеки: {имя: ProviderSpec}."""
    return {
        name: spec
        for name, module in PROVIDER_MODULES.items()
        if (spec := getattr(module, "SPEC", None)) is not None
    }


def max_provider_timeout_sec() -> float:
    """Наибольший таймаут ОДНОГО обращения к провайдеру, из фактических настроек.

    Нужен тем, кто ставит СВОЙ дедлайн поверх вызова: внешний срок, который жёстче
    транспортного, делает ответ невозможным по построению — провайдер ещё имеет право
    отвечать, а нас уже нет. Ровно так и жил синтез веб-поиска: `wait_for(..., 20)` при
    `routerai_timeout_sec=45` и `openai` с дефолтом 60 — на медленном провайдере
    пользователь ВСЕГДА получал «таймаут» и сырую выдачу вместо ответа.

    Тот же приём, что у бюджета поиска (`search_engine_timeout_sec`): второе число не
    задаём, а выводим — два независимых значения уже разъезжались однажды.
    """
    from .providers.spec import settings_value

    values = [
        float(settings_value(spec.timeout_field) or spec.default_timeout_sec)
        for spec in all_specs().values()
    ]
    return max(values) if values else 60.0


def is_configured(name: str) -> bool:
    """Провайдер считается готовым, если у него есть инициализированный клиент."""
    module = get_provider_module(name)
    if module is None:
        return False
    return getattr(module, "OPENAI_CLIENT", None) is not None


def _parse_fallback_order() -> list[str]:
    default_order = config.agents.provider_fallback_order
    raw = (runtime_settings.get_agents("provider_fallback_order", default_order) or "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def build_provider_order(primary: str) -> list[str]:
    """Очередь провайдеров: primary первым, затем сконфигурированный fallback-список.

    При выключенном фейловере (пустой ``provider_fallback_order`` или флаг off)
    возвращает только ``[primary]`` — поведение идентично прежнему.
    """
    from . import provider_policy

    disabled = provider_policy.disabled_providers()  # выключенные админом — не пробуем
    primary = (primary or "").strip().lower()
    order: list[str] = [primary] if primary and primary not in disabled else []

    if not runtime_settings.get_agents(
        "provider_failover_enabled", config.agents.provider_failover_enabled
    ):
        return order

    for name in _parse_fallback_order():
        if name in order or name in disabled:
            continue
        if name not in PROVIDER_MODULES:
            logger.warning("Unknown provider '%s' in AGENTS__PROVIDER_FALLBACK_ORDER", name)
            continue
        if not is_configured(name):
            continue
        order.append(name)
    return order


def _pick_chat_capable_model(models: list[str], prefer: str | None = None) -> str | None:
    """Заменитель модели у провайдера, куда ушёл фейловер.

    Раньше здесь стояло просто ``pool[0]`` — ПЕРВАЯ модель списка. А списки отсортированы
    по алфавиту, и первой оказывалась ``ai21/jamba-large-1.7``: модель класса `large`,
    в 15 раз дороже за токен. Живой случай: человек выбрал claude-haiku (`fast`), у
    OpenRouter кончился лимит ключа, фейловер ушёл на RouterAI — и те же 17k токенов
    стоили 4505 кредитов вместо 396.

    Теперь заменитель не может быть ДОРОЖЕ выбранного класса. Если у провайдера нет
    ничего подходящего — возвращаем None, и фейловер идёт к следующему: ответить чужой
    дорогой моделью молча хуже, чем спросить соседа.

    Потолок цены в ``_charge_usage`` остаётся второй линией обороны: класс — эвристика
    по имени, и она может ошибиться.
    """
    filtered = [
        m for m in (models or []) if not any(b in m.lower() for b in _BLOCKED_MODEL_MARKERS)
    ]
    pool = filtered
    if not pool:
        return None
    affordable = [m for m in pool if is_not_pricier_than(m, prefer)]
    if affordable:
        return affordable[0]
    if prefer:
        logger.warning(
            "У провайдера нет модели не дороже выбранной '%s' — пропускаем его, "
            "чтобы не выставить счёт за нашу подмену",
            prefer,
        )
        return None
    return pool[0]


async def _fetch_provider_catalogs(
    *,
    clients: dict[str, object] | None = None,
    configuration_keys: dict[str, str] | None = None,
    generation_catalogs: dict[str, ProviderModelCatalog] | None = None,
) -> dict[str, ProviderModelCatalog]:
    """Модели по каждому СКОНФИГУРИРОВАННОМУ провайдеру (у кого есть клиент).

    Провайдеры опрашиваются ПАРАЛЛЕЛЬНО: недоступный провайдер (таймаут /models,
    напр. GigaChat при недостижимом Сбере) не должен добавлять свою задержку
    последовательно — иначе холодный каталог собирается десятки секунд (сумма
    таймаутов вместо максимума одного).
    """
    from . import circuit_breaker, provider_policy

    names = (
        [name for name, client in clients.items() if client is not None]
        if clients is not None
        else [
            name
            for name, module in PROVIDER_MODULES.items()
            if getattr(module, "OPENAI_CLIENT", None) is not None
        ]
    )

    # 1) disabled (админ выключил) + blocked (health-блок) — прячем ВСЕГДА, даже если это
    # опустошит пикер: это осознанное решение админа/проверки, а не временный сбой.
    hard = await provider_policy.hard_off(names)
    if hard:
        logger.info("Каталог: прячу выключенные/заблокированные провайдеры: %s", sorted(hard))
    names = [n for n in names if n not in hard]

    # 2) circuit_breaker.down — временный (429/таймаут) сигнал из трафика воркера, долетает
    # до API-пикера только через Redis. Тут защита «не опустошай»: если после этого никого
    # не осталось (напр. свежий процесс, ещё никто не пробовал) — не прячем, фейловер
    # подстрахует. Для disabled/blocked такой поблажки нет (см. выше).
    down = await circuit_breaker.down_providers(names)
    if down:
        logger.info("Каталог: прячу модели упавших провайдеров (breaker): %s", sorted(down))
    live = [n for n in names if n not in down]
    names = live or names

    async def _one(name: str) -> ProviderModelCatalog:
        if generation_catalogs is not None and name in generation_catalogs:
            return generation_catalogs[name]
        return await get_provider_model_catalog(
            name,
            client=clients.get(name) if clients is not None else None,
            configuration_key=(configuration_keys or {}).get(name),
        )

    results = await asyncio.gather(*(_one(n) for n in names))
    return dict(zip(names, results, strict=True))


async def initialize_run_provider_admission(execution) -> RunProviderAdmission:
    """Freeze provider catalogs, clients and qualification evidence for one run."""

    if execution.provider_admission is not None:
        return execution.provider_admission
    from .provider_snapshot import build_run_provider_admission

    execution.provider_admission = await build_run_provider_admission()
    return execution.provider_admission


async def _fetch_grouped_models() -> dict[str, list[str]]:
    """Compatibility projection for catalog/UI callers that need full inventory."""

    catalogs = await _fetch_provider_catalogs()
    return {name: list(catalog.models) for name, catalog in catalogs.items()}


async def build_model_catalog(active: str) -> tuple[list[str], dict[str, str]]:
    """Compatibility facade over the typed provider inventory builder."""

    from .provider_inventory import build_model_catalog as build

    return await build(active)


async def build_qualified_model_catalog(
    active: str,
    *,
    requirement: ModelRequirement | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Compatibility facade over run-scoped or process-scoped qualification."""

    from .provider_inventory import build_qualified_model_catalog as build

    return await build(active, requirement=requirement)


async def list_qualified_models(
    requirement: ModelRequirement | None = None,
) -> list[str]:
    """Return the qualified aggregate while keeping the legacy inventory facade intact."""

    from service.domain.run_context import current_execution

    from .active import get_active_provider

    execution = current_execution()
    if execution is not None and execution.provider_admission is not None:
        admission = execution.provider_admission
        models, _ = admission.qualified_catalog(
            requirement or ModelRequirement(),
            pick_model=_pick_chat_capable_model,
        )
        return models

    models, _ = await build_qualified_model_catalog(
        get_active_provider(),
        requirement=requirement,
    )
    return models


async def get_provider_model_catalog(
    provider_name: str,
    *,
    force_refresh: bool = False,
    client: object | None = None,
    configuration_key: str | None = None,
) -> ProviderModelCatalog:
    """Read one provider inventory without erasing discovery provenance."""
    normalized = (provider_name or "").strip().lower()
    module = get_provider_module(normalized)
    if module is None:
        return ProviderModelCatalog(
            provider=normalized,
            models=(),
            source=ModelCatalogSource.STATIC_FALLBACK,
            status=ModelCatalogStatus.UNAVAILABLE,
            fresh=False,
        )

    runtime = getattr(module, "_RUNTIME", None)
    if runtime is not None and hasattr(runtime, "model_catalog"):
        return await runtime.model_catalog(
            client=client,
            force_refresh=force_refresh,
            configuration_key=configuration_key,
        )

    # Compatibility providers and test doubles may expose only the old list method.
    # A successful empty list remains authoritative.
    try:
        models = tuple(await module.list_available_models())
    except Exception:
        spec = getattr(module, "SPEC", None)
        fallback = tuple(getattr(spec, "fallback_models", ()) or ())
        return ProviderModelCatalog(
            provider=normalized,
            models=fallback,
            source=ModelCatalogSource.STATIC_FALLBACK,
            status=ModelCatalogStatus.UNAVAILABLE,
            fresh=False,
        )
    return ProviderModelCatalog(
        provider=normalized,
        models=models,
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE if models else ModelCatalogStatus.EMPTY,
        fresh=True,
    )


async def qualify_model(
    provider_name: str,
    *,
    prefer: str | None = None,
    requirement: ModelRequirement | None = None,
    force_refresh: bool = False,
    catalog: ProviderModelCatalog | None = None,
) -> ModelQualification:
    """Select a compatible model and retain the evidence used for the decision."""
    normalized = (provider_name or "").strip().lower()
    effective = requirement or ModelRequirement()
    if catalog is None and not force_refresh:
        from service.domain.run_context import current_execution

        execution = current_execution()
        if execution is not None and execution.provider_admission is not None:
            admission = execution.provider_admission
            return admission.qualify(
                normalized,
                requirement=effective,
                prefer=prefer,
                pick_model=_pick_chat_capable_model,
            )
    effective_catalog = catalog or await get_provider_model_catalog(
        normalized, force_refresh=force_refresh
    )
    return await qualify_catalog(
        provider=normalized,
        requirement=effective,
        spec=get_spec(normalized),
        catalog=effective_catalog,
        prefer=prefer,
        is_chat_capable=is_chat_capable,
        pick_model=_pick_chat_capable_model,
    )


async def resolve_model_for(
    provider_name: str,
    *,
    prefer: str | None = None,
    requirement: ModelRequirement | None = None,
) -> str | None:
    """Подобрать модель, валидную для конкретного провайдера.

    Если ``prefer`` присутствует в списке моделей провайдера — берём её; иначе
    выбираем первую chat-способную из его собственного списка.
    """
    decision = await qualify_model(
        provider_name,
        prefer=prefer,
        requirement=requirement,
    )
    return decision.model


async def _keep_same_modality(models: list[str], prefer: str) -> list[str]:
    """Keep vision requests on explicitly evidenced vision-capable chat models."""
    try:
        from service.shared.model_catalog import get_openrouter_catalog, model_has_capability

        catalog = await get_openrouter_catalog()
        if not model_has_capability(prefer, "vision", catalog):
            return models
        seeing = [
            m for m in models if model_has_capability(m, "vision", catalog) and is_chat_capable(m)
        ]
    except Exception:  # noqa: BLE001 — неизвестная capability не считается подтверждённой
        logger.debug("model catalog unavailable", extra={"failure_code": "unavailable"})
        return []
    if not seeing:
        logger.warning(
            "У провайдера нет зрячей замены для '%s' — провайдер пропущен",
            prefer,
        )
    return seeing
