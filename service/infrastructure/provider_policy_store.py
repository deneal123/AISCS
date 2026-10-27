"""Провайдерская политика — ХРАНИЛИЩЕ backend'а (persistent-состояние).

Владелец состояния — backend: ручной чекбокс админа живёт в его runtime-настройках, а
health-блоки в его БД (``profile.app_settings``) и Redis. Пишут сюда админ-панель и
celery-beat, читает — панель.

Сайдкар этим модулем НЕ пользуется: политику он получает СНИМКОМ в теле ``/run``
(``service.shared.provider_policy_context``). Раньше обе роли жили в одном модуле внутри
домена, и backend ради своего же состояния тащил чужое дерево.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from service.settings import config

logger = logging.getLogger(__name__)
_DIAGNOSTIC_CODES = frozenset(
    {
        "redis_unavailable",
        "prime_failed",
        "redis_seed_failed",
        "blocks_restored",
        "persist_failed",
        "redis_block_failed",
        "provider_blocked",
        "redis_clear_failed",
        "provider_unblocked",
        "redis_read_failed",
    }
)


def _diagnostic(level: int, code: str) -> None:
    # Codes are static call-site constants. Provider names, health reasons and
    # exception bodies belong to private state, never diagnostic formatting.
    logger.log(
        level,
        "provider policy operation",
        extra={
            "component": "provider_policy",
            "failure_code": code if code in _DIAGNOSTIC_CODES else "policy_failed",
        },
    )


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
        _diagnostic(logging.WARNING, "redis_unavailable")
        _redis = None
    return _redis


# Имена провайдеров. Реестр модулей живёт в домене (сайдкар), а backend'у для хранения
# политики нужны только ИМЕНА — держим их списком, чтобы не тащить чужой пакет.
# ⚠️ Появится новый провайдер — добавить сюда, иначе его блокировки не будут читаться.
PROVIDER_NAMES: tuple[str, ...] = ("mws", "openai", "openrouter", "gigachat", "routerai", "local")


def _all_provider_names() -> list[str]:
    return list(PROVIDER_NAMES)


# ------------------------------------------------------------------ disabled --
def _enabled_map() -> dict[str, bool]:
    from service.shared.agent_settings_port import runtime_settings

    raw = runtime_settings.get_agents("provider_enabled", config.agents.provider_enabled)
    return raw if isinstance(raw, dict) else {}


def disabled_providers() -> set[str]:
    """Провайдеры, ВЫКЛЮЧЕННЫЕ админом вручную (чекбокс). Отсутствие ключа = включён."""
    return {str(name) for name, on in _enabled_map().items() if not on}


# ------------------------------------------------------------------- blocked --
async def prime() -> None:
    """Загрузить persistent-блоки из БД в Redis + in-memory (на старте процесса)."""
    if _repo is None:
        return
    try:
        settings = await _repo.get_all()
    except Exception:  # noqa: BLE001
        _diagnostic(logging.DEBUG, "prime_failed")
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
                _diagnostic(logging.DEBUG, "redis_seed_failed")
    if _BLOCKED:
        _diagnostic(logging.INFO, "blocks_restored")


async def _persist_db() -> None:
    """Сохранить текущее in-memory зеркало в БД (источник истины для рестарта)."""
    if _repo is None:
        return
    ts = int(time.time())
    payload = {name: {"reason": reason, "ts": ts} for name, reason in _BLOCKED.items()}
    try:
        await _repo.upsert(key=_DB_KEY, value=payload, updated_by="provider_policy")
    except Exception:  # noqa: BLE001
        _diagnostic(logging.WARNING, "persist_failed")


async def set_blocked(name: str, reason: str) -> None:
    """Заблокировать провайдера (health-проверка упала). persistent: БД + Redis + память."""
    name = (name or "").strip().lower()
    if not name:
        return
    _BLOCKED[name] = (reason or "blocked")[:160]
    r = _get_redis()
    if r is not None:
        try:
            await asyncio.to_thread(r.set, _REDIS_KEY.format(name=name), _BLOCKED[name])
        except Exception:  # noqa: BLE001
            _diagnostic(logging.DEBUG, "redis_block_failed")
    await _persist_db()
    _diagnostic(logging.WARNING, "provider_blocked")


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
            _diagnostic(logging.DEBUG, "redis_clear_failed")
    await _persist_db()
    _diagnostic(logging.INFO, "provider_unblocked")


async def blocked_providers(names: list[str] | None = None) -> set[str]:
    """Кросс-процессный список заблокированных: Redis (авторитетно) ∪ in-memory зеркало."""
    names = names or _all_provider_names()
    blocked = {n for n in names if n in _BLOCKED}
    r = _get_redis()
    if r is None:
        return blocked
    try:
        vals = await asyncio.to_thread(r.mget, [_REDIS_KEY.format(name=n) for n in names])
        blocked |= {n for n, v in zip(names, vals, strict=True) if v is not None}
    except Exception:  # noqa: BLE001
        _diagnostic(logging.DEBUG, "redis_read_failed")
    return blocked
