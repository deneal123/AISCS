"""Настройки САЙДКАРА — только то, что он читает.

Раньше сайдкар импортировал конфиг backend'а целиком: 28 классов, 20 секций, 818 строк, из
которых он читал ДВЕ секции (`agents`, `redis`) и ~440 строк грузил, ни разу не прочитав. Это
и была главная статья общего пакета — не контракт, а чужой конфиг.

Здесь копия ровно нужного. Копия, а не импорт: конфигурация — не контракт между сервисами, у
каждого он свой, и backend вправе добавлять секции, не спрашивая нас.

⚠️ ИМЕНА ПЕРЕМЕННЫХ НЕ МЕНЯЛИСЬ НИ РАЗУ: `env_prefix` переезжал вместе с классами, поэтому
compose и `.env.*` продолжают работать как есть. Это условие безопасности любого переноса —
переименование хоть одной переменной означало бы тихую потерю настройки.

⚠️ Пакет, а не файл: `AgentsConfig` дорос до 133 полей, и потолок в 500 строк был бы пробит
раньше, чем заработал MCP или workspace. Класс при этом остался ОДИН — разбиты только поля,
по темам (`providers`, `sidecars`, `pipeline`). Импорт `from service.settings import config`
у потребителей не изменился.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ._empty import EmptyStringMeansUnset
from .agents import AgentsConfig
from .pipeline import Agents, PipelineSettings, _default_personas
from .providers import ProviderSettings
from .redis import Redis, RedisConfig
from .sidecars import SidecarSettings


class Config(BaseSettings):
    """Корень конфигурации сайдкара: две секции, которые он действительно читает.

    У backend в этом месте 20 секций (БД, MinIO, почта, платежи, JWT…). Ни одна из них
    сайдкару не нужна: состояние приходит в теле запроса, токенов он не выпускает, в
    хранилища не ходит. Отсутствие секции — не упущение, а граница сервиса.
    """

    # ⚠️ `default_factory`, а НЕ готовый экземпляр. Экземпляр в теле класса создаётся один раз
    # на импорте модуля и навсегда запоминает окружение того момента: конфиг переставал быть
    # конструируемым, а тест не мог собрать его под другим env. Так же объявлено у backend.
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)

    # Без `env_nested_delimiter` вложенные секции не читаются из окружения ВОВСЕ: весь блок
    # `REDIS__*` из compose молча отбрасывался. У backend этот параметр есть; при копировании
    # конфига в сайдкар корневой класс остался без него.
    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")


config = Config()

__all__ = [
    "Agents",
    "AgentsConfig",
    "Config",
    "EmptyStringMeansUnset",
    "PipelineSettings",
    "ProviderSettings",
    "Redis",
    "RedisConfig",
    "SidecarSettings",
    "_default_personas",
    "config",
]
