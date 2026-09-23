"""Активный провайдер: выбор, привязка SDK и пересборка после смены ключа.

Единственный дом ИЗМЕНЯЕМОГО состояния клиентского слоя. Здесь живут три имени —
`_ACTIVE`, `ACTIVE_PROVIDER`, `OPENAI_CLIENT`, — и их меняет `rebuild_provider()`,
когда админ заменил ключ провайдера в панели.

⚠️ ПРАВИЛО, БЕЗ КОТОРОГО РАЗДЕЛЕНИЕ ЛОМАЕТ ФУНКЦИЮ. Соседние модули обязаны читать эти
имена ЧЕРЕЗ МОДУЛЬ (`from . import active` → `active.ACTIVE_PROVIDER`) и никогда не
делать `from .active import ACTIVE_PROVIDER`. Второе связывает ЗНАЧЕНИЕ на момент
импорта: после `rebuild_provider()` модуль продолжил бы работать со старым провайдером,
не падая и ничего не логируя. Симптом был бы ровно тот, который эта платформа уже
однажды ловила, — «заменил мёртвый ключ в админке, ничего не починилось».

Держит правило `tests/test_active_provider_rebind.py`.
"""

from __future__ import annotations

import logging

from service.settings import config

from .providers._sdk import (
    set_default_openai_client,
    set_default_openai_key,
    set_tracing_disabled,
)

logger = logging.getLogger(__name__)


def _ordered_specs() -> list[tuple[str, object]]:
    """Спеки в порядке авто-выбора. Импорт отложенный: реестр тянет все провайдер-модули."""
    from .registry import all_specs

    return sorted(all_specs().items(), key=lambda kv: kv[1].auto_select_priority)


def _looks_configured(spec) -> bool:
    """Есть ли у провайдера хоть одно заполненное поле, по которому его берут в auto."""
    fields = spec.auto_select_fields or (spec.api_key_field,)
    return any(getattr(config.agents, name, "") for name in fields)


def _select_active_provider():
    """Выбрать активного провайдера для high-level API.

    Правило прежнее: явный `llm_provider` в приоритете, иначе перебор по спекам в порядке
    `auto_select_priority` до первого, у которого что-то настроено, иначе — первый по
    этому же порядку как заглушка (вызовы упадут с понятной ошибкой).

    ⚠️ Здесь были ДВЕ if/elif цепочки — одна для явного выбора, вторая для авто, — и обе
    перечисляли провайдеров поимённо. Добавляя провайдера, надо было вписать себя в обе;
    пропуск любой давал провайдера, которого нельзя выбрать, причём молча.
    """
    from .registry import get_provider_module

    explicit = (config.agents.llm_provider or "auto").strip().lower()
    ordered = _ordered_specs()

    if explicit and explicit != "auto":
        module = get_provider_module(explicit)
        if module is not None:
            return module

    for name, spec in ordered:
        if _looks_configured(spec):
            return get_provider_module(name)

    return get_provider_module(ordered[0][0]) if ordered else None


def _bind_agents_sdk_defaults(active_module) -> None:
    """Привязать дефолты OpenAI Agents SDK ТОЛЬКО к выбранному провайдеру.

    Иначе каждый импортированный провайдер-модуль пытался бы выставить глобальные
    дефолты SDK на себя, и побеждал бы последний импортированный — а не выбранный.
    """
    try:
        client = getattr(active_module, "OPENAI_CLIENT", None)
        api_key = getattr(active_module, "OPENAI_API_KEY", None)
        if client is not None:
            set_default_openai_client(client)
        if api_key:
            set_default_openai_key(str(api_key))
        set_tracing_disabled(disabled=True)
    except Exception:
        logger.debug("Agents SDK provider binding failed code=internal")


def _provider_name_of(module) -> str:
    """Имя провайдера берётся у САМОГО МОДУЛЯ.

    ⚠️ Здесь стояла карта `{id(mws_client): "mws", …}` — обратный поиск по `id()`
    объекта. Провайдер, забытый в ней, получал имя чужого провайдера (по умолчанию
    "mws"), и в трейсе, биллинге и политике он значился НЕ ТЕМ, кем был.
    """
    return str(getattr(module, "PROVIDER_NAME", "") or "")


_ACTIVE = _select_active_provider()
ACTIVE_PROVIDER = _provider_name_of(_ACTIVE)
_bind_agents_sdk_defaults(_ACTIVE)

# Ссылка на клиент активного провайдера — для совместимости с SDK и существующим кодом.
OPENAI_CLIENT = getattr(_ACTIVE, "OPENAI_CLIENT", None)


def get_active_provider() -> str:
    """Имя активного провайдера: 'mws', 'openai', 'openrouter', 'gigachat', 'routerai'."""
    return ACTIVE_PROVIDER


def get_openai_client():
    """Низкоуровневый клиент АКТИВНОГО провайдера.

    ⚠️ Здесь запасной путь возвращал `openai_client.OPENAI_CLIENT` — клиент нативного
    OpenAI, кто бы ни был активен. Появился он потому, что у `openai` одного не было
    хелпера `get_openai_client`; но провайдер, добавленный без этого метода, молча
    получал бы ЧУЖОЙ клиент: запросы ушли бы не туда, с чужим ключом и в чужой биллинг.
    Фабрика теперь даёт метод всем, а запас читает состояние САМОГО активного.
    """
    if hasattr(_ACTIVE, "get_openai_client"):
        return _ACTIVE.get_openai_client()
    return getattr(_ACTIVE, "OPENAI_CLIENT", None)


def clear_models_cache() -> None:
    """Очистить кеш моделей активного провайдера (если он его поддерживает)."""
    if hasattr(_ACTIVE, "clear_models_cache"):
        return _ACTIVE.clear_models_cache()
    return None


def rebuild_provider(name: str) -> bool:
    """Пересобрать клиента провайдера после замены его API-ключа (без рестарта стека).

    Провайдер-модуль перечитывает ключ через provider_credentials и строит новый
    AsyncOpenAI. Затем переселектим активного провайдера (новый ключ мог сделать его
    пригодным) и перепривязываем Agents SDK к активному — фабрики внутри могли
    перебиндить SDK-дефолты на себя. Фасад и реестр читают ``module.OPENAI_CLIENT``
    динамически, поэтому фейловер и каталог сразу видят свежий клиент.
    """
    from .registry import get_provider_module

    module = get_provider_module(name)
    rebuild = getattr(module, "rebuild_client", None) if module is not None else None
    if rebuild is None:
        return False
    try:
        rebuild()
    except Exception:
        logger.error("provider client rebuild failed code=internal")
        return False

    # The provider-local cache is cleared by ``rebuild``.  The aggregate catalog
    # must be invalidated as well or a rotated key/base URL can leave its old model
    # inventory authoritative until the global TTL expires.
    from .calls.catalog import invalidate_model_catalog

    invalidate_model_catalog()

    global _ACTIVE, ACTIVE_PROVIDER, OPENAI_CLIENT
    _ACTIVE = _select_active_provider()
    ACTIVE_PROVIDER = _provider_name_of(_ACTIVE) or ACTIVE_PROVIDER
    _bind_agents_sdk_defaults(_ACTIVE)
    OPENAI_CLIENT = getattr(_ACTIVE, "OPENAI_CLIENT", None)
    return True


async def rebuild_provider_generation(name: str) -> bool:
    """Prepare and atomically publish a complete provider generation for new runs."""

    from .registry import get_provider_module

    module = get_provider_module(name)
    runtime = getattr(module, "_RUNTIME", None) if module is not None else None
    if runtime is None or not hasattr(runtime, "rebuild_generation"):
        return rebuild_provider(name)
    try:
        await runtime.rebuild_generation()
    except Exception:  # noqa: BLE001 - new runs see bounded unavailable state
        logger.error("provider generation rebuild failed code=internal")
        return False

    from .calls.catalog import invalidate_model_catalog

    invalidate_model_catalog()
    global _ACTIVE, ACTIVE_PROVIDER, OPENAI_CLIENT
    _ACTIVE = _select_active_provider()
    ACTIVE_PROVIDER = _provider_name_of(_ACTIVE) or ACTIVE_PROVIDER
    _bind_agents_sdk_defaults(_ACTIVE)
    OPENAI_CLIENT = getattr(_ACTIVE, "OPENAI_CLIENT", None)
    return True
