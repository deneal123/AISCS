"""Agent integrations package.

Contains pluggable adapters for external services used by agent layer
(for example memory providers).
"""

from __future__ import annotations

import logging

from service.infrastructure.memory.base import (
    BaseIntegration,
    BaseMemoryIntegration,
    NoopMemoryIntegration,
)
from service.infrastructure.memory.mem0 import Mem0MemoryIntegration
from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.settings import config

logger = logging.getLogger(__name__)

_memory_integration_singleton: BaseMemoryIntegration | None = None


def _build_memory_integration() -> BaseMemoryIntegration:
    """Выбрать провайдера памяти по AGENTS__MEMORY_PROVIDER.

    auto (по умолчанию): mem0 → memos → noop (сохраняем прежний приоритет).
    Явные значения: mem0 | memos | noop.
    """
    from service.shared.agent_settings_port import runtime_settings

    provider = (
        (runtime_settings.get_agents("memory_provider", config.agents.memory_provider) or "auto")
        .strip()
        .lower()
    )

    if provider == "noop":
        return NoopMemoryIntegration()
    if provider == "memos":
        memos = MemOSMemoryIntegration()
        return memos if memos.available else NoopMemoryIntegration()
    if provider == "mem0":
        mem0 = Mem0MemoryIntegration()
        return mem0 if mem0.available else NoopMemoryIntegration()

    # auto
    mem0 = Mem0MemoryIntegration()
    if mem0.available:
        return mem0
    memos = MemOSMemoryIntegration()
    if memos.available:
        return memos
    return NoopMemoryIntegration()


def get_memory_integration() -> BaseMemoryIntegration:
    """Return singleton memory integration used by agent/services layer."""
    global _memory_integration_singleton
    if _memory_integration_singleton is None:
        integration = _build_memory_integration()
        _memory_integration_singleton = integration
        if integration.available:
            logger.info("Долговременная память включена (%s)", integration.name)
        else:
            # Видимая деградация: кросс-сессионная память отключена. Память в рамках
            # текущей сессии (история сообщений) продолжает работать.
            logger.warning(
                "Долговременная память ОТКЛЮЧЕНА: провайдер не сконфигурирован "
                "(mem0: MEM0_API_KEY; memos: AGENTS__MEMOS_BASE_URL). "
                "Память в рамках сессии (история) работает."
            )
    return _memory_integration_singleton


def reset_memory_integration_singleton() -> None:
    """Сбросить кэш-синглтон выбранного провайдера (используется в тестах)."""
    global _memory_integration_singleton
    _memory_integration_singleton = None


__all__ = [
    "BaseIntegration",
    "BaseMemoryIntegration",
    "NoopMemoryIntegration",
    "Mem0MemoryIntegration",
    "MemOSMemoryIntegration",
    "get_memory_integration",
    "reset_memory_integration_singleton",
]
