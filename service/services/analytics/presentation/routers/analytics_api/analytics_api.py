from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request

from service.composition.state import get_analytics_service
from service.services.analytics.application.analytics_service import AnalyticsService
from service.services.analytics.presentation.routers.analytics_api.schemas import (
    IngestAcceptedResponse,
    VitalsBatchIn,
    VitalsSummaryResponse,
)

analytics_router = APIRouter(prefix="/api/analytics")


@analytics_router.post("/vitals", response_model=IngestAcceptedResponse)
async def ingest_vitals(
    payload: Annotated[VitalsBatchIn, Body()],
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> IngestAcceptedResponse:
    enqueued = await service.ingest_vitals(payload.model_dump(mode="json"))
    return IngestAcceptedResponse(accepted=True, enqueued=enqueued)


@analytics_router.get("/vitals/summary", response_model=VitalsSummaryResponse)
async def vitals_summary(
    service: Annotated[AnalyticsService, Depends(get_analytics_service)],
) -> VitalsSummaryResponse:
    result = await service.fetch_summary()
    return VitalsSummaryResponse.model_validate(result)


@analytics_router.get("/public", summary="Public project stats for hero (no auth)")
async def public_stats(request: Request) -> dict:
    """Обезличенная агрегированная статистика для hero: пользователей, потрачено токенов,
    посещений. Публичный (без auth). Счётчик визитов инкрементится раз в сутки на посетителя
    (дедуп по хэшу IP) — иначе накручивался на каждый хит."""
    from service.services.analytics.application.public_stats import get_public_stats

    ip = (request.client.host if request.client else "") or ""
    # Хэшируем IP: в Redis-маркере не держим сырой адрес (обезличенность метрики).
    visitor_id = hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else None
    return await get_public_stats(visitor_id=visitor_id)


@analytics_router.get("/memos-embedder", summary="MemOS embedder config for the memos service")
async def memos_embedder_config() -> dict:
    """Эмбеддер MemOS (модель + размерность) из runtime-настроек админки с фолбэком на
    config/env. Читается сервисом memos при старте — так админ-выбор эмбеддера
    применяется после рестарта memos (без правки env). Без auth (несекретно)."""
    from service.services.admin.application.runtime_settings import runtime_settings
    from service.settings import config

    model = runtime_settings.get_agents("memos_embedder_model", config.agents.memos_embedder_model)
    dim = runtime_settings.get_agents("memos_embedder_dim", config.agents.memos_embedder_dim)
    return {"model": str(model or ""), "dimension": int(dim or 0)}
