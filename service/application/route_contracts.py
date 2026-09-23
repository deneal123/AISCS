"""Решение роутера и текст отказа — то, что сайдкар ОТДАЁТ наружу.

Жило в общем пакете вместе с внутренними типами оркестрации chat, которых сайдкар
не видел никогда. Здесь только своё: структура решения (её `/route` сериализует в
словарь — контракт держится проводом, а не общим классом) и текст, которым
отвечаем, когда ни один провайдер не ответил.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatRouteDecision:
    """Решение роутера. `/route` сериализует его в словарь — контракт держится проводом.

    Поля покрыты `ROUTE_RESPONSE_FIELDS` и сверяются с ожиданиями backend: `routing_usage`
    тарифицируется отдельно, `selected_model` уходит в резерв кредитов.
    """

    selected_model: str | None
    routing_metadata: dict[str, Any] = field(default_factory=dict)
    web_search: bool = False
    deep_research: bool = False
    route_override: str | None = None
    # usage LLM-роутера (посчитан при resolve_route в веб-процессе) — везём в воркер
    # для отдельной тарификации (аудит A2). Пусто, если роутер-LLM не звался.
    routing_usage: dict[str, Any] = field(default_factory=dict)
    # Категория агента, уже выбранная авто-роутером. Едет ОТДЕЛЬНЫМ полем, а не через
    # `route_override`, и это не стилистика.
    #
    # ⚠️ `route_override` — это ФОРСИРОВАНИЕ инструмента, и на нём висят гейты:
    # `processor_steps` отключает по нему И мульти-интент декомпозицию, И оценку
    # сложности с построением плана. Положи мы категорию туда, самый частый запрос
    # (авто-режим, инструмент не нужен) молча лишился бы планирования и разбора на
    # подзадачи — и выглядело бы это как ускорение, а было бы падением качества.
    #
    # Пусто, когда авто-роутер не звался (ручной выбор модели: `route_model`
    # короткозамыкается в `source:"manual"` БЕЗ LLM-вызова) — тогда категорию по-прежнему
    # определяет роутер внутри `/run`, и никакого дублирования там нет.
    resolved_category: str | None = None


def build_provider_unavailable_reply(error_message: str | None = None) -> str:
    base = (
        "Сейчас не удалось получить ответ от модели. "
        "Проверьте API-ключ/доступ к провайдеру и повторите запрос."
    )
    if error_message:
        return f"{base} Детали: {error_message}"
    return base
