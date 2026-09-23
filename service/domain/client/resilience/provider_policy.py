"""Политика доступности провайдеров: кого админ выключил и кого health-блок «убил».

Три состояния «недоступен», у каждого своя природа:

* **disabled** — РУЧНОЙ выбор админа (чекбокс). Живёт в runtime-настройке
  ``agents.provider_enabled`` (json-мапа ``{name: bool}``; нет ключа/пусто = все включены).
  Читается синхронно из ``runtime_settings`` (кросс-процессно через короткий TTL).
* **blocked** — АВТО health-блок: живая проверка провайдера упала, и он заблокирован,
  пока следующая проверка не пройдёт. persistent (переживает рестарт, в отличие от
  circuit_breaker): источник истины — ``profile.app_settings`` ключ ``provider_blocked``,
  быстрое кросс-процессное чтение — Redis ``provider:blocked:{name}`` БЕЗ TTL, плюс
  in-memory зеркало на процесс. Праймится из БД на старте.
* **down** (circuit_breaker) — транзитный 90с авто-кулдаун из трафика воркера.

``unavailable_providers`` объединяет все три — это ЕДИНСТВЕННАЯ функция, которую потребляют
каталог моделей, порядок фейловера и шлюз. ``hard_off`` = disabled ∪ blocked (осознанные
решения — прячем/не пробуем ВСЕГДА, даже если это опустошит список); circuit_breaker.down
остаётся с защитой «не опустошай» для временных 429.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from service.settings import config
from service.shared import provider_policy_context

logger = logging.getLogger(__name__)

_DB_KEY = "provider_blocked"
_REDIS_KEY = "provider:blocked:{name}"

# In-memory зеркало blocked-состояния (name -> reason) на процесс. Быстрое чтение и
# фолбэк, когда Redis недоступен. Праймится из БД/Redis на старте.
_BLOCKED: dict[str, str] = {}

# Ленивый репозиторий app_settings для durability (bind на старте, как у runtime_settings).
_repo: Any | None = None

# Синхронный Redis (не loop-bound) — тот же приём, что в circuit_breaker: celery крутит
# новый loop на задачу, async-клиент падал бы «attached to a different loop».
_redis = None
_redis_ready = False


def bind(repo: Any) -> None:
    """Привязать AppSettingsRepository (на старте процесса) для persistent-хранения."""
    global _repo
    _repo = repo


def _get_redis():
    global _redis, _redis_ready
    if _redis_ready:
        return _redis
    _redis_ready = True
    try:
        if not getattr(config.redis, "enabled", False):
            return None
        import redis

        _redis = redis.Redis.from_url(config.redis.dsn, decode_responses=True)
    except Exception:  # noqa: BLE001 - Redis необязателен, деградируем до памяти
        logger.warning("provider_policy: Redis недоступен, остаюсь на in-memory")
        _redis = None
    return _redis


def _all_provider_names() -> list[str]:
    # ⚠️ `..registry`, А НЕ `.registry`. Модуль переехал в подпакет `resilience/`, а
    # относительный импорт остался прежним — и стал резолвиться в несуществующий
    # `client.resilience.registry`. Ветка редкая (сюда попадают, только когда `hard_off`
    # зовут БЕЗ явного списка провайдеров), поэтому ModuleNotFoundError не всплывал:
    # `_fetch_grouped_models` передаёт имена, а на пустом списке — как при старте без
    # настроенных провайдеров — падал сбор каталога целиком, и каталог оставался пустым.
    from ..registry import PROVIDER_MODULES

    return list(PROVIDER_MODULES.keys())


# ------------------------------------------------------------------ disabled --
def _enabled_map() -> dict[str, bool]:
    from service.shared.agent_settings import runtime_settings

    raw = runtime_settings.get_agents("provider_enabled", config.agents.provider_enabled)
    return raw if isinstance(raw, dict) else {}


def disabled_providers() -> set[str]:
    """Провайдеры, ВЫКЛЮЧЕННЫЕ админом вручную (чекбокс). Отсутствие ключа = включён.

    В сайдкаре runtime-настройки backend'а недоступны (админ-overlay живёт в его БД), и
    без снимка мы бы молча вернули пустое множество — то есть выключенный провайдер снова
    пошёл бы в работу. Поэтому сначала смотрим снимок из тела ``/run``.
    """
    passed = provider_policy_context.get_disabled()
    if passed is not None:
        return set(passed)
    return {str(name) for name, on in _enabled_map().items() if not on}


# ------------------------------------------------------------------- blocked --
async def prime() -> None:
    """Загрузить persistent-блоки из БД в Redis + in-memory (на старте процесса)."""
    if _repo is None:
        return
    try:
        settings = await _repo.get_all()
    except Exception:  # noqa: BLE001
        logger.debug("provider policy prime unavailable", extra={"failure_code": "unavailable"})
        return
    stored = settings.get(_DB_KEY)
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except Exception:  # noqa: BLE001
            stored = {}
    if not isinstance(stored, dict):
        return
    _BLOCKED.clear()
    r = _get_redis()
    for name, meta in stored.items():
        reason = str((meta or {}).get("reason", "blocked")) if isinstance(meta, dict) else "blocked"
        _BLOCKED[str(name)] = reason
        if r is not None:
            try:
                await asyncio.to_thread(r.set, _REDIS_KEY.format(name=name), reason)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "provider policy cache seed unavailable",
                    extra={"component": name, "failure_code": "unavailable"},
                )
    if _BLOCKED:
        logger.info("provider_policy: восстановлены блоки провайдеров: %s", sorted(_BLOCKED))


async def _persist_db() -> None:
    """Сохранить текущее in-memory зеркало в БД (источник истины для рестарта)."""
    if _repo is None:
        return
    ts = int(time.time())
    payload = {name: {"reason": reason, "ts": ts} for name, reason in _BLOCKED.items()}
    try:
        await _repo.upsert(key=_DB_KEY, value=payload, updated_by="provider_policy")
    except Exception:  # noqa: BLE001
        logger.warning("provider policy persistence failed code=unavailable")


async def set_blocked(name: str, reason: str) -> None:
    """Заблокировать провайдера (health-проверка упала). persistent: БД + Redis + память."""
    name = (name or "").strip().lower()
    if not name:
        return
    allowed_reasons = {
        "auth",
        "quota",
        "rate_limit",
        "timeout",
        "transport",
        "tls",
        "tls_config",
        "remote",
        "internal",
        "blocked",
    }
    _BLOCKED[name] = reason if reason in allowed_reasons else "blocked"
    r = _get_redis()
    if r is not None:
        try:
            await asyncio.to_thread(r.set, _REDIS_KEY.format(name=name), _BLOCKED[name])
        except Exception:  # noqa: BLE001
            logger.debug("provider policy cache failed code=unavailable")
    await _persist_db()
    logger.warning(
        "provider blocked",
        extra={"component": name, "failure_code": _BLOCKED[name]},
    )


async def clear_blocked(name: str) -> None:
    """Снять блок (проверка прошла). Идемпотентно."""
    name = (name or "").strip().lower()
    if name not in _BLOCKED and _get_redis() is None:
        return
    _BLOCKED.pop(name, None)
    r = _get_redis()
    if r is not None:
        try:
            await asyncio.to_thread(r.delete, _REDIS_KEY.format(name=name))
        except Exception:  # noqa: BLE001
            logger.debug(
                "provider policy cache update unavailable",
                extra={"component": name, "failure_code": "unavailable"},
            )
    await _persist_db()
    logger.info("provider_policy: провайдер '%s' разблокирован", name)


async def blocked_providers(names: list[str] | None = None) -> set[str]:
    """Кросс-процессный список заблокированных: Redis (авторитетно) ∪ in-memory зеркало.

    Снимок из тела ``/run`` (сайдкар) главнее: его источник — БД+Redis backend'а, где
    health-блоки и живут, а у сайдкара этих хранилищ нет.
    """
    passed = provider_policy_context.get_blocked()
    if passed is not None:
        return {n for n in (names or _all_provider_names()) if n in passed}
    names = names or _all_provider_names()
    blocked = {n for n in names if n in _BLOCKED}
    r = _get_redis()
    if r is None:
        return blocked
    try:
        vals = await asyncio.to_thread(r.mget, [_REDIS_KEY.format(name=n) for n in names])
        blocked |= {n for n, v in zip(names, vals, strict=True) if v is not None}
    except Exception:  # noqa: BLE001
        logger.debug("provider policy cache unavailable", extra={"failure_code": "unavailable"})
    return blocked


# ----------------------------------------------------------- комбинированные --
async def hard_off(names: list[str] | None = None) -> set[str]:
    """disabled ∪ blocked — осознанные решения (админ/health): прячем/не пробуем ВСЕГДА."""
    names = names or _all_provider_names()
    return disabled_providers() | await blocked_providers(names)


async def unavailable_providers(names: list[str] | None = None) -> set[str]:
    """disabled ∪ blocked ∪ circuit_breaker.down — полная недоступность."""
    from . import circuit_breaker

    names = names or _all_provider_names()
    return await hard_off(names) | await circuit_breaker.down_providers(names)


async def drop_hard_off(order: list[str]) -> list[str]:
    """Убрать disabled+blocked из порядка попыток. МОЖЕТ опустошить (админ вырубил всё —
    это осознанно; вызывающий обязан обработать пустой список)."""
    off = await hard_off(order)
    return [n for n in order if n not in off]
