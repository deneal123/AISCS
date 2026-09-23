"""Единая точка импорта биндеров OpenAI Agents SDK — он опционален.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Этот блок try/except был скопирован ПЯТЬ раз: в каждый из
четырёх провайдер-клиентов и в `active`. Тела совпадали побайтово, различались только
комментарии у `except` — то есть копии уже начали расходиться в мелочах, и ничто не
мешало им разойтись по существу.

Фолбэк нужен по-настоящему: пакет `agents` есть не во всяком окружении (минимальные
сборки, часть тестовых прогонов), а импортировать его жёстко значит уронить весь
клиентский слой там, где SDK не нужен вовсе. Заглушки — no-op: единственный потребитель
этих функций, `active._bind_agents_sdk_defaults`, привязывает ГЛОБАЛЬНЫЕ дефолты SDK, и
их отсутствие ничего не ломает.

⚠️ Импортировать отсюда ИМЕНА, а не модуль: биндеры не перепривязываются в рантайме, так
что связывание значением здесь безопасно — в отличие от `active.ACTIVE_PROVIDER`.
"""

from __future__ import annotations

try:
    from agents import (
        set_default_openai_api,
        set_default_openai_client,
        set_default_openai_key,
        set_tracing_disabled,
    )
except Exception:  # pragma: no cover — минимальные окружения без Agents SDK

    def set_default_openai_client(_client):
        return None

    def set_default_openai_key(_key):
        return None

    def set_tracing_disabled(*, disabled: bool):
        return None

    def set_default_openai_api(_api):
        return None


__all__ = [
    "set_default_openai_api",
    "set_default_openai_client",
    "set_default_openai_key",
    "set_tracing_disabled",
]
