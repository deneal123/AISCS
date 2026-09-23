"""`AgentsConfig` — единственный класс с префиксом `AGENTS__`.

Поля собраны из тематических примесей, но класс остаётся ОДИН: `env_prefix` и `extra="forbid"`
обязаны быть в одном месте, иначе незаявленная переменная перестанет ронять старт громко — а
это единственное, что ловит опечатку в имени настройки.

⚠️ Порядок баз тематический и на поведение не влияет: поля pydantic собирает по MRO, валидаторы
примесей применяются к полям итогового класса.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from ._empty import EmptyStringMeansUnset
from .pipeline import PipelineSettings
from .providers import ProviderSettings
from .sidecars import SidecarSettings


class AgentsConfig(
    PipelineSettings, ProviderSettings, SidecarSettings, EmptyStringMeansUnset, BaseSettings
):
    model_config = SettingsConfigDict(env_prefix="AGENTS__")
