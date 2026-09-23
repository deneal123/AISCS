"""Сборка субагентов — тонкая обёртка над реестром способностей.

⚠️ Здесь был литеральный словарь `{"general": GeneralAgent(...), ...}` — первое из девяти
мест, где имя агента писалось второй раз. Теперь набор выводится из объявленных спек, а
модуль остаётся точкой входа: его зовёт `Orchestrator`.
"""

from service.domain.base import BaseAgent
from service.domain.capabilities import build_agents


def build_subagents(model_settings: dict | None = None) -> dict[str, BaseAgent]:
    """Собрать все объявленные субагенты."""
    return build_agents(model_settings)
