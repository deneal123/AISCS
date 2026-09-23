"""`POST /route` — роутинг-решение ДО диспатча (для резерва кредитов в веб-процессе)."""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from service.contracts import ROUTE_RESPONSE_FIELDS  # noqa: F401 — ре-экспорт
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.presentation import runtime
from service.presentation.deps import internal_auth
from service.presentation.errors import error
from service.schemas.route import RouteRequest

router = APIRouter()


@router.post("/route")
async def route(payload: RouteRequest, authorization: str | None = Header(default=None)) -> dict:
    """Роутинг-решение ДО диспатча: какой моделью и каким агентом обрабатывать запрос.

    Роутер — это ЛЛМ-вызов. Исторически он делался в веб-процессе backend'а, и после
    выноса движка это оставляло второе место, где backend звонит провайдерам сам: своим
    клиентом, со своим breaker'ом и своим представлением о выключенных. Теперь решение
    принимает тот, кто провайдерами владеет.

    ⚠️ ``routing_usage`` — токены роутер-ЛЛМ, по которым воркер ОТДЕЛЬНО тарифицирует
    пользователя. Отдаём как есть: потеряется — вызов достанется бесплатно.
    """
    internal_auth(authorization)
    if runtime.ModelRoutingService is None:
        return error("routing_unavailable", "unavailable", 503)
    try:
        with use_run_execution(PrivateRunResources()) as execution:
            from service.domain.client.registry import initialize_run_provider_admission

            await initialize_run_provider_admission(execution)
            decision = await runtime.ModelRoutingService().resolve_route(
                text=payload.text,
                selected_model=payload.selected_model,
                input_type=payload.input_type,
                web_search=payload.web_search,
                deep_research=payload.deep_research,
                route_override=payload.route_override,
                execution=execution,
            )
    except runtime.ModelRoutingError:
        # Роутер сработал, но решения не дал (провайдеры молчат и т.п.). Это НЕ
        # «сервиса нет» — backend отличит 502 от 503 и не спутает с недеплоем.
        return JSONResponse(
            status_code=502,
            content={"error": "routing_failed", "detail": "unavailable"},
        )
    return {
        "selected_model": decision.selected_model,
        "routing_metadata": dict(decision.routing_metadata or {}),
        "web_search": bool(decision.web_search),
        "deep_research": bool(decision.deep_research),
        "route_override": decision.route_override,
        "routing_usage": dict(decision.routing_usage or {}),
        "resolved_category": decision.resolved_category,
    }
