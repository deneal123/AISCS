"""Порт runtime-настроек агентов на стороне backend — намеренный DIP-шов.

Зачем прокси, а не прямой вызов админки: настройки читает `service/infrastructure/*`
(graphify, память, провайдерная политика, скачивание репозитория), а живут они в
`service/services/admin/application/`. Прямой импорт был бы инверсией слоёв —
инфраструктура не должна знать про прикладной слой. Поэтому инфраструктура зовёт порт,
а admin-модуль регистрирует себя в нём на импорте (`set_provider`).

Без регистрации порт возвращает `default`. Это не заглушка «на всякий случай», а
fail-safe: overlay без привязанного репозитория ведёт себя ровно так же.

⚠️ Половина ПОТРЕБИТЕЛЯ снимка (ContextVar прогона, процессная память, `use_settings`)
сюда НЕ копируется: снимок админ-настроек нужен сайдкару, у которого нет БД backend'а.
У backend БД есть, он читает overlay напрямую — и заводить ему вторую, снимочную,
дорогу к тем же данным значило бы создать два расходящихся представления.
"""

from __future__ import annotations

from typing import Any, Protocol


class AgentSettingsProvider(Protocol):
    """Что должен уметь провайдер overlay для агентских настроек."""

    def get_agents(self, name: str, default: Any = None) -> Any: ...


class _DefaultProvider:
    """До регистрации admin-overlay отдаём дефолт — как overlay без репозитория."""

    def get_agents(self, name: str, default: Any = None) -> Any:
        return default


class _AgentSettingsProxy:
    """Объект, который импортит инфраструктура. Делегирует зарегистрированному провайдеру."""

    def __init__(self) -> None:
        self._provider: AgentSettingsProvider = _DefaultProvider()

    def set_provider(self, provider: AgentSettingsProvider) -> None:
        """Admin-модуль вызывает на импорте, подавая свою overlay-реализацию."""
        self._provider = provider

    def get_agents(self, name: str, default: Any = None) -> Any:
        return self._provider.get_agents(name, default)


runtime_settings = _AgentSettingsProxy()
