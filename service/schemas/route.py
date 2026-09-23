"""Контракт ``POST /route`` сайдкара agents (остаток Фазы 4).

Роутер решает, какой моделью и каким агентом обрабатывать сообщение, — и делает это
ЛЛМ-вызовом. Исторически он срабатывал в ВЕБ-процессе backend'а (до диспатча в очередь,
чтобы зарезервировать кредиты под выбранную модель). После выноса движка это оставляло
второе место, где backend сам звонит провайдерам: со своим клиентом, своим breaker'ом и
своим представлением о том, кто выключен, — мимо всего, чем теперь владеет сайдкар.

⚠️ Ответ несёт ``routing_usage`` — токены ЛЛМ-роутера, по которым воркер ОТДЕЛЬНО
тарифицирует пользователя. Поле обязано пережить сериализацию: потеряется — пользователь
получит вызов бесплатно, исказится — заплатит не за то.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RouteRequest(BaseModel):
    """Тело ``POST /route`` — вход ``resolve_route``."""

    text: str
    selected_model: str | None = None
    input_type: str | None = None
    web_search: bool = False
    deep_research: bool = False
    route_override: str | None = None

    model_config = ConfigDict(extra="ignore")
