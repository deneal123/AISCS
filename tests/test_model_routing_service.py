"""Роутинг со стороны backend: он теперь ТОЛЬКО клиент сайдкара.

Раньше здесь проверялась локальная ветка ``resolve_route``: подменялся ``route_model`` из
домена и сверялось, как метаданные роутера превращаются во флаги. Эта логика уехала
вместе с доменом — теперь она живёт и тестируется в сайдкаре (``test_model_router.py``
и соседи в ветке ``agents``).

У backend осталась одна обязанность: спросить сайдкар и честно доложить, если тот не
ответил. Разбор ответа проверяется в ``test_sidecar_route.py``.
"""

import pytest

from service.services.chat.application.model_routing_service import ModelRoutingService
from service.services.chat.domain.chat_exceptions import ModelRoutingError


@pytest.mark.asyncio
async def test_raises_domain_error_when_sidecar_is_silent(monkeypatch) -> None:
    """Локального роутера больше нет — молча слать «как есть» нельзя.

    ``ModelRoutingError`` ловит ``chat_service`` и отправляет сообщение с моделью,
    которую выбрал пользователь: сообщение всё равно уходит, но факт «роутинг не
    сработал» остаётся видимым, а не растворяется в тишине.
    """

    async def _no_sidecar(self, **payload):
        return None

    monkeypatch.setattr(ModelRoutingService, "_resolve_via_sidecar", _no_sidecar)

    with pytest.raises(ModelRoutingError):
        await ModelRoutingService().resolve_route(
            text="q",
            selected_model=None,
            input_type=None,
            web_search=False,
            deep_research=False,
            route_override=None,
        )


@pytest.mark.asyncio
async def test_returns_sidecar_decision_as_is(monkeypatch) -> None:
    """Решение сайдкара backend не переосмысливает — иначе трактовки разъедутся."""
    from service.services.chat.domain.chat_contracts import ChatRouteDecision

    decision = ChatRouteDecision(
        selected_model="openai:gpt-4o-mini",
        routing_metadata={"tool": "web_search"},
        web_search=True,
        routing_usage={"total": 128},
    )

    async def _from_sidecar(self, **payload):
        return decision

    monkeypatch.setattr(ModelRoutingService, "_resolve_via_sidecar", _from_sidecar)

    got = await ModelRoutingService().resolve_route(
        text="q",
        selected_model=None,
        input_type=None,
        web_search=False,
        deep_research=False,
        route_override=None,
    )

    assert got is decision
    # Токены роутера — денежное поле: воркер тарифицирует их отдельно.
    assert got.routing_usage == {"total": 128}
