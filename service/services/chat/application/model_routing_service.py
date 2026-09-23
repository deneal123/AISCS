import logging

from service.services.chat.domain.chat_contracts import ChatRouteDecision

logger = logging.getLogger(__name__)


class ModelRoutingService:
    async def _resolve_via_sidecar(self, **payload) -> ChatRouteDecision | None:
        """Спросить роутинг у сайдкара. ``None`` = не смогли, решай локально.

        ⚠️ ``routing_usage`` тащим бережно: по нему воркер ОТДЕЛЬНО тарифицирует токены
        роутер-ЛЛМ. Потеряем — вызов достанется пользователю бесплатно.
        """
        from service.settings import config

        base = str(getattr(config.agents, "sidecar_url", "") or "").rstrip("/")
        if not base:
            return None
        timeout = float(getattr(config.agents, "sidecar_timeout_sec", 600.0) or 600.0)
        try:
            import httpx

            # ⚠️ Ключ обязателен: сайдкар закрыл `/route` (ручка решает, какой моделью
            # обрабатывать запрос, и её ответ тарифицируется). Без заголовка — 401.
            key = str(getattr(config.agents, "llm_gateway_api_key", "") or "")
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            async with httpx.AsyncClient(timeout=min(timeout, 60.0)) as client:
                resp = await client.post(f"{base}/route", json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.warning("agents sidecar: /route вернул HTTP %s", resp.status_code)
                return None
            data = resp.json()
        except Exception:  # noqa: BLE001 — fail-open: без роутинга сообщение не уйдёт
            logger.warning("agents sidecar: /route недоступен", exc_info=True)
            return None
        if not isinstance(data, dict) or "selected_model" not in data:
            logger.warning("agents sidecar: неожиданная форма ответа /route")
            return None
        return ChatRouteDecision(
            selected_model=data.get("selected_model"),
            routing_metadata=dict(data.get("routing_metadata") or {}),
            web_search=bool(data.get("web_search")),
            deep_research=bool(data.get("deep_research")),
            route_override=data.get("route_override"),
            routing_usage=dict(data.get("routing_usage") or {}),
            resolved_category=data.get("resolved_category"),
        )

    async def resolve_route(
        self,
        text: str,
        selected_model: str | None,
        input_type: str | None,
        web_search: bool,
        deep_research: bool,
        route_override: str | None,
    ) -> ChatRouteDecision:
        # Роутер живёт в САЙДКАРЕ: он владеет провайдерами, и решать «какой моделью»
        # должен тот, кто знает, какие модели вообще доступны.
        sidecar_decision = await self._resolve_via_sidecar(
            text=text,
            selected_model=selected_model,
            input_type=input_type,
            web_search=web_search,
            deep_research=deep_research,
            route_override=route_override,
        )
        if sidecar_decision is not None:
            return sidecar_decision

        # Локального роутера больше нет: домен уехал в сайдкар. Не ответил — поднимаем
        # доменную ошибку, а НЕ молча шлём как есть: chat_service её ловит и отправляет
        # сообщение с моделью, которую выбрал пользователь. То есть сообщение уходит,
        # но факт «роутинг не сработал» остаётся видимым в логе, а не растворяется.
        from service.services.chat.domain.chat_exceptions import ModelRoutingError

        raise ModelRoutingError("Роутинг недоступен: сервис агентов не отвечает")
