"""Клиент к ``/providers/*`` и ``/catalog/*`` сайдкара agents.

Зачем ходить по HTTP за тем, что backend умеет посчитать сам: после флипа
``AGENTS__ENGINE_MODE=http`` провайдерам звонит САЙДКАР. Значит и здоровье надо мерить
оттуда — локальная проба backend'а отвечает на другой вопрос («доступен ли провайдер
из backend»), а его circuit_breaker после переезда трафика пуст и о реальных отказах
не знает.

Fail-open: не достучались — возвращаем ``None``, и вызывающий считает сам, как раньше.
Панель здоровья не должна гаснуть из-за того, что сайдкар моргнул. Но решение
деградировать принимает ВЫЗЫВАЮЩИЙ, явно поймав исключение, — не транспорт молча.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from service.infrastructure.sidecar import SidecarClient, SidecarError

logger = logging.getLogger(__name__)

# ⚠️ Таймауты ПООПЕРАЦИОННЫЕ, и это не нарушение правила «источник один». Правило бьёт
# по случаю, когда ОДНУ И ТУ ЖЕ операцию разные вызывающие ждут по-разному (у graphify
# было 900/60/30 на один класс). Здесь операции разной природы: проба пяти провайдеров
# и запись ключа в память — не одно и то же, и общий срок был бы неверен для обеих.
# Объявлены они в ОДНОМ месте на модуль, а не в вызовах.
#
# Проба ходит к 5 провайдерам с таймаутом ~5с каждая; они идут параллельно, но холодный
# старт (резолв моделей + баланс) реально занимает секунды. Берём с запасом: этот путь
# не на каждом показе панели, а только на холодном кэше и по кнопке «Проверить».
HEALTH_TIMEOUT_SEC = 30.0

# Доставка ключей — короткая операция (запись в память + пересборка клиента), но она на
# пути замены ключа в панели: лучше подождать пару секунд, чем оставить сайдкар со старым.
KEYS_TIMEOUT_SEC = 10.0


def _client(config: Any, timeout: float) -> SidecarClient:
    agents_cfg = getattr(config, "agents", None)
    return SidecarClient(
        service="agents",
        base_url=str(getattr(agents_cfg, "sidecar_url", "") or ""),
        timeout=timeout,
        # ⚠️ Ключ нужен ВСЕМ ручкам здесь. Раньше он уходил только на `/providers/keys`,
        # а три GET-ручки звались без него — и работали лишь потому, что сайдкар их не
        # проверял. Теперь проверяет: без заголовка это 401.
        api_key=str(getattr(agents_cfg, "llm_gateway_api_key", "") or ""),
    )


async def fetch_provider_health(
    config: Any, *, force_probe: bool = False, only: Sequence[str] | None = None
) -> dict[str, Any] | None:
    """Здоровье провайдеров с сайдкара. ``None`` = не смогли, считай локально.

    ``only`` — спросить ТОЧЕЧНО перечисленных. Проба на той стороне это настоящий вызов
    к провайдеру, поэтому периодическая самопроверка заблокированных обязана называть их
    поимённо, а не форсировать обход всех.
    """
    params: dict[str, str] = {"force": str(bool(force_probe)).lower()}
    if only is not None:
        params["only"] = ",".join(only)
    try:
        data = await _client(config, HEALTH_TIMEOUT_SEC).request_json(
            "GET",
            "/providers/health",
            params=params,
        )
    except SidecarError as exc:
        logger.warning("agents sidecar: /providers/health недоступен (%s)", exc.code)
        return None

    # Минимальная проверка формы: панель ждёт providers-словарь. Мусор лучше отвергнуть
    # и посчитать локально, чем отрисовать пустую таблицу «всё сломано».
    if not isinstance(data.get("providers"), dict):
        logger.warning("agents sidecar: неожиданная форма ответа /providers/health")
        return None
    return data


async def fetch_chat_model_catalog(
    config: Any, *, chat_only: bool = False
) -> tuple[list[str], dict[str, str]] | None:
    """Каталог чат-моделей с сайдкара: ``(модели, model_id → провайдер)``.

    ``None`` = не смогли; вызывающий (биллинг) деградирует к своему прежнему пути. Пустой
    каталог — НЕ то же самое: он означает «провайдеры ничего не отдали», и подменять им
    отказ связи нельзя, иначе прайс-лист молча схлопнется.
    """
    try:
        data = await _client(config, HEALTH_TIMEOUT_SEC).request_json(
            "GET",
            "/catalog/chat-models",
            params={"chat_only": str(bool(chat_only)).lower()},
        )
    except SidecarError as exc:
        logger.warning("agents sidecar: /catalog/chat-models недоступен (%s)", exc.code)
        return None
    if not isinstance(data.get("models"), list):
        logger.warning("agents sidecar: неожиданная форма /catalog/chat-models")
        return None
    owners = data.get("owners")
    return list(data["models"]), dict(owners) if isinstance(owners, dict) else {}


async def fetch_keys_version(config: Any) -> int | None:
    """Версия набора ключей, применённая в сайдкаре. ``None`` = не смогли спросить."""
    try:
        data = await _client(config, KEYS_TIMEOUT_SEC).request_json("GET", "/health")
    except SidecarError:
        logger.debug(
            "agents integration failure",
            extra={"component": "provider_keys", "failure_code": "unavailable"},
        )
        return None
    version = (data.get("provider_keys") or {}).get("version")
    return int(version) if isinstance(version, int) else None


async def push_provider_keys(config: Any, *, version: int, overrides: dict[str, str]) -> bool:
    """Отправить снимок провайдерских ключей в сайдкар. ``False`` = не доставили.

    ⚠️ В теле СЕКРЕТЫ: ни значения, ни их длины не логируем — только имена провайдеров.
    """
    try:
        await _client(config, KEYS_TIMEOUT_SEC).request(
            "POST",
            "/providers/keys",
            json_body={"version": int(version), "overrides": overrides},
        )
    except SidecarError as exc:
        logger.warning(
            "agents sidecar: не доставили ключи провайдеров %s (%s) — он останется на "
            "ключах из env, и замена ключа в панели не подействует",
            sorted(overrides),
            exc.code,
        )
        return False
    return True


async def fetch_agent_catalog(config: Any) -> dict[str, dict] | None:
    """Каталог агентов с сайдкара: `{имя: {label_ru, cost_class}}`. `None` — СПРОСИТЬ НЕ СМОГЛИ.

    🔴 `None`, А НЕ ПУСТОЙ СЛОВАРЬ, и разница здесь решающая. Пустой означал бы «агентов
    нет», и вызывающий отверг бы любой шаг как несуществующий; `None` означает «не знаем»,
    и решение принимает он. Тот же приём, что у каталога моделей: там пустой список
    однажды снял инструменты со ВСЕХ моделей.

    ⚠️ Своего списка агентов у backend НЕТ и заводить его нельзя: он разошёлся бы с
    реестром сайдкара молча.
    """
    try:
        data = await _client(config, HEALTH_TIMEOUT_SEC).request_json("GET", "/catalog/agents")
    except SidecarError as exc:
        logger.warning("agents sidecar: /catalog/agents недоступен (%s)", exc.code)
        return None
    items = data.get("agents")
    if not isinstance(items, dict) or not items:
        logger.warning("agents sidecar: неожиданная форма /catalog/agents")
        return None
    return items


async def fetch_persona_catalog(config: Any) -> list[dict[str, str]]:
    """Каталог личностей с сайдкара: ``[{id, label}]``, только включённые.

    Пустой список при сбое — НАМЕРЕННО, в отличие от каталога моделей. Там `None`
    означает «спросить не смогли» и включает деградацию биллинга; здесь спрашивает
    ПИКЕР, и «личностей нет» — честное состояние интерфейса: без реестра выбирать всё
    равно нечего, а ронять чат из-за недоступного селектора нельзя.
    """
    try:
        data = await _client(config, HEALTH_TIMEOUT_SEC).request_json("GET", "/catalog/personas")
    except SidecarError as exc:
        logger.warning("agents sidecar: /catalog/personas недоступен (%s)", exc.code)
        return []
    items = data.get("personas")
    if not isinstance(items, list):
        logger.warning("agents sidecar: неожиданная форма /catalog/personas")
        return []
    # ⚠️ `hint` ПЕРЕНОСИМ, а не отбрасываем. Пояснение живёт в реестре сайдкара именно
    # затем, чтобы новая личность из админского JSON объясняла себя без выката фронта;
    # ре-проекция «только id и label» молча превращала это в фолбэк «Специализация из
    # реестра админки» у ВСЕХ шести. Тот же класс потери, что был у `kind` в
    # `per_call_usage`: поле есть у источника и исчезает на нормализации у потребителя.
    return [
        {
            "id": str(i["id"]),
            "label": str(i.get("label") or i["id"]),
            "hint": str(i.get("hint") or ""),
        }
        for i in items
        if isinstance(i, dict) and i.get("id")
    ]
