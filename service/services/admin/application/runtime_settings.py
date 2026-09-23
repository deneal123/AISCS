"""Runtime-overlay настроек: DB-значения поверх статичного config (fail-safe).

Singleton ``runtime_settings`` читается живым кодом (billing/agents) вместо
прямого ``config.X`` для зарегистрированных ключей. Кэш с коротким TTL (как кэш
моделей в mws_client) даёт меж-процессную свежесть (backend ↔ celery-worker) без
шины. Любая ошибка/недоступность БД → отдаём дефолт из ``config`` (поведение как
до админки). Чтения синхронны (хот-путь чата не блокируется): берём in-memory
снапшот, а при истёкшем TTL запускаем обновление fire-and-forget.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from service.services.admin.application.settings_registry import REGISTRY, SettingSpec
from service.settings import config
from service.shared.agent_settings_port import runtime_settings as _agents_rs_proxy

logger = logging.getLogger(__name__)

_STALE_BACKOFF_SEC = 5.0  # чтобы не молотить БД при ошибках


class RuntimeSettings:
    def __init__(self) -> None:
        self._repo: Any | None = None
        self._repo_loop: asyncio.AbstractEventLoop | None = None
        self._cache: dict[str, Any] = {}
        self._expires_at: float = 0.0
        # Лок создаётся ЛЕНИВО и привязывается к текущему event loop. Синглтон живёт весь
        # процесс, а celery-воркер крутит loop-per-task (новый loop на каждый таск) — лок,
        # привязанный к первому (уже закрытому) loop, ронял refresh с "bound to a different
        # event loop". Пересоздаём при смене loop (как per-loop клиенты в circuit_breaker).
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    def bind(self, repo: Any) -> None:
        """Привязать AppSettingsRepository (на старте процесса)."""
        self._repo = repo
        try:
            self._repo_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._repo_loop = None

    def ensure_bound(self, factory: Any) -> None:
        """Идемпотентно привязать репозиторий (для воркер-процесса, ленивый bind)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        # Celery opens a fresh loop for every synchronous task. Repositories
        # retain asyncpg pools, so they must not outlive the loop that owns them.
        if self._repo is None or (loop is not None and self._repo_loop is not loop):
            self._repo = factory()
            self._repo_loop = loop

    @property
    def is_bound(self) -> bool:
        return self._repo is not None

    def _ttl(self) -> float:
        try:
            return float(config.admin.settings_overlay_ttl_sec or 30)
        except Exception:
            return 30.0

    def invalidate(self) -> None:
        self._expires_at = 0.0

    async def refresh(self, *, force: bool = False) -> None:
        if self._repo is None:
            return
        if not force and time.monotonic() < self._expires_at:
            return
        async with self._get_lock():
            if not force and time.monotonic() < self._expires_at:
                return
            try:
                items = await self._repo.get_all()
                self._cache = items if isinstance(items, dict) else {}
                self._expires_at = time.monotonic() + self._ttl()
            except Exception:
                logger.debug("runtime settings refresh failed; keep stale/defaults", exc_info=True)
                self._expires_at = time.monotonic() + _STALE_BACKOFF_SEC

    def _raw(self, key: str) -> Any:
        """Синхронный снапшот значения + fire-and-forget refresh при устаревании."""
        if self._repo is not None and time.monotonic() >= self._expires_at:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.refresh())
            except RuntimeError:
                pass  # нет event loop (sync-контекст) — обновимся при следующем async-доступе
        return self._cache.get(key)

    @staticmethod
    def _clamp(value: float, spec: SettingSpec) -> float:
        if spec.minimum is not None:
            value = max(value, spec.minimum)
        if spec.maximum is not None:
            value = min(value, spec.maximum)
        return value

    def _coerce(self, spec: SettingSpec, raw: Any, default: Any) -> Any:
        try:
            if spec.type == "bool":
                if isinstance(raw, bool):
                    return raw
                return str(raw).strip().lower() in {"1", "true", "yes", "on"}
            if spec.type == "int":
                return int(self._clamp(int(raw), spec))
            if spec.type == "float":
                return float(self._clamp(float(raw), spec))
            if spec.type == "str":
                return str(raw)
            if spec.type == "json":
                return raw if isinstance(raw, (dict, list)) else default
        except (ValueError, TypeError):
            return default
        return default

    def get(self, key: str, default: Any = None) -> Any:
        spec = REGISTRY.get(key)
        if spec is None:
            return default  # вне whitelist — overlay недоступен
        raw = self._raw(key)
        if raw is None:
            return default
        return self._coerce(spec, raw, default)

    def get_billing(self, name: str, default: Any = None) -> Any:
        return self.get(f"billing.{name}", default)

    def get_agents(self, name: str, default: Any = None) -> Any:
        return self.get(f"agents.{name}", default)

    def snapshot_agents(self) -> dict[str, Any]:
        """Слепок ПЕРЕОПРЕДЕЛЁННЫХ админом настроек агентов — для тела ``/run``.

        Сайдкар в admin-БД не ходит, поэтому без слепка он отдал бы движку дефолты, и
        админ-тумблеры (выключить duckdb/graphify, поднять ретраи, сменить порядок
        фейловера) в http-режиме молча перестали бы действовать.

        Кладём ТОЛЬКО то, что реально переопределено: чего нет в слепке — сайдкар возьмёт
        из своего конфига, как и раньше. Значения прогоняем через ``_coerce``, чтобы на
        той стороне оказался уже типизированный и зажатый в границы результат, а не сырая
        строка из БД.
        """
        snapshot: dict[str, Any] = {}
        for key, spec in REGISTRY.items():
            if spec.section != "agents":
                continue
            raw = self._raw(key)
            if raw is None:
                continue
            name = key.split(".", 1)[1]
            value = self._coerce(spec, raw, None)
            if value is not None:
                snapshot[name] = value
        return snapshot


runtime_settings = RuntimeSettings()

# Регистрируем этот admin-overlay синглтон как провайдера порта агентского домена
# (service.shared.agent_settings_port): домен зовёт прокси, а тот делегирует СЮДА. В сайдкаре
# этот модуль не импортится → прокси остаётся с no-overlay дефолтом (вернуть default),
# что совпадает с поведением overlay без привязанного репозитория. Инверсия зависимости:
# Инфраструктура админку НЕ импортит — backend сам себя подаёт (граница не нарушена).
_agents_rs_proxy.set_provider(runtime_settings)


class OverlayBillingConfig:
    """Прокси поверх ``config.billing``: зарегистрированные поля берутся из overlay,
    остальные делегируются базе. Drop-in замена для ``self._cfg`` в Billing/Pricing.
    """

    def __init__(self, base: Any, rs: RuntimeSettings | None = None) -> None:
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_rs", rs or runtime_settings)

    def __getattr__(self, name: str) -> Any:
        base = object.__getattribute__(self, "_base")
        rs = object.__getattribute__(self, "_rs")
        default = getattr(base, name)
        key = f"billing.{name}"
        if key in REGISTRY:
            return rs.get(key, default)
        return default
