"""Админ-настройки агентов на стороне САЙДКАРА — снимок из тела запроса.

Overlay админки (тумблеры duckdb/graphify, ретраи, лимиты контекста, порядок
фейловера) живёт в БД backend'а. Сайдкар туда не ходит, поэтому переопределения
приезжают снимком в теле ``/run`` и разворачиваются здесь на время прогона.

Без снимка отдаём ``default`` — то есть выключенный админом инструмент молча
включился бы обратно. Ровно поэтому снимок и появился.

⚠️ ``describe_settings().provider`` не для красоты: затащишь в сайдкар admin-модуль
backend'а — он зарегистрирует себя провайдером на импорте и МОЛЧА вытеснит снимок.
Увидеть это можно только так.

Половина backend'а (его собственный DIP-прокси к админке) живёт у него в
``service/shared/agent_settings_port.py`` и сюда не копируется: у него есть БД, он
читает overlay напрямую, и вторая, снимочная, дорога к тем же данным создала бы два
расходящихся представления.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any, Protocol

# Снимок админ-overlay на время одного прогона (сайдкар). Тот же приём, что и с
# провайдерной политикой: overlay живёт в БД backend'а, сайдкар туда не ходит, поэтому
# значения приезжают в теле ``/run``. Без снимка сайдкар отдавал бы ДЕФОЛТЫ, то есть
# админ-тумблеры (выключить duckdb/graphify, поднять ретраи, сменить порядок фейловера)
# в http-режиме молча переставали бы действовать.
_SNAPSHOT: ContextVar[dict[str, Any] | None] = ContextVar(
    "gpthub_agent_settings_snapshot", default=None
)

# Последний виденный процессом снимок — для путей без своего (``/v1``): см. тот же
# компромисс и его границу в ``provider_policy_context``.
_LAST_SEEN: dict[str, Any] | None = None


class RuntimeSettingsProvider(Protocol):
    """Что должен уметь провайдер overlay для агентского домена."""

    def get_agents(self, name: str, default: Any = None) -> Any: ...


class _SnapshotProvider:
    """Провайдер по умолчанию: overlay из снимка запроса, иначе ``default``.

    Нет снимка (backend in-process, юнит-тесты) → ведёт себя ровно как прежний
    no-overlay провайдер. Ключа нет в снимке → тоже ``default``: снимок несёт ТОЛЬКО
    реально переопределённое админом, а не весь конфиг.
    """

    def get_agents(self, name: str, default: Any = None) -> Any:
        snapshot = _SNAPSHOT.get()
        if snapshot is None:
            snapshot = _LAST_SEEN
        if snapshot is not None and name in snapshot:
            return snapshot[name]
        return default


def remember_settings(payload: Any) -> None:
    """Запомнить снимок на процесс (сайдкар зовёт из ``/run``) — ради путей без своего."""
    global _LAST_SEEN
    if isinstance(payload, dict):
        _LAST_SEEN = dict(payload)


@contextlib.contextmanager
def use_settings(payload: Any) -> Iterator[None]:
    """Применить снимок админ-настроек на время прогона (сторона сайдкара)."""
    if not isinstance(payload, dict):
        yield
        return
    token = _SNAPSHOT.set(dict(payload))
    try:
        yield
    finally:
        _SNAPSHOT.reset(token)


def describe_settings() -> dict[str, Any]:
    """Состояние для ``/health``: какие админ-переопределения знает сайдкар и КТО их отдаёт.

    ``provider`` здесь не для красоты: если в сайдкар случайно затащить admin-модуль
    backend'а, тот зарегистрирует себя провайдером (он делает это на импорте) и МОЛЧА
    вытеснит снимок — настройки снова поедут по дефолтам. Видно это только так.
    """
    return {
        "known": _LAST_SEEN is not None,
        "keys": sorted(_LAST_SEEN or {}),
        "provider": type(runtime_settings._provider).__name__,
    }


class _RuntimeSettingsProxy:
    """Объект, который импортит домен. Делегирует зарегистрированному провайдеру
    (backend admin-overlay) либо дефолту (сайдкар — overlay нет)."""

    def __init__(self) -> None:
        self._provider: RuntimeSettingsProvider = _SnapshotProvider()

    def set_provider(self, provider: RuntimeSettingsProvider) -> None:
        """Backend вызывает на старте, подавая свою admin-overlay реализацию."""
        self._provider = provider

    def get_agents(self, name: str, default: Any = None) -> Any:
        return self._provider.get_agents(name, default)


# Синглтон, который импортирует агентский домен: ``from service.shared.agent_settings
# import runtime_settings``.
runtime_settings = _RuntimeSettingsProxy()
