"""API графа знаний пользователя: что в нём лежит, поиск, сброс.

Граф — личный (`user-{user_id}`) и копится МЕЖДУ тредами, в отличие от файла в Redis,
который жил один на тред и умирал по TTL. Поэтому у него должна быть своя поверхность:
пользователь обязан видеть, что о нём накопили, и уметь это стереть.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from service.infrastructure.graphify import GraphifyClient, user_graph_id
from service.models.auth_models import AuthProfile
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)
graph_router = APIRouter(prefix="/api/graph")


def _graph_id(profile: AuthProfile) -> str:
    graph_id = user_graph_id(str(profile.user_id))
    if not graph_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id is required")
    return graph_id


@graph_router.get("/summary")
async def get_graph_summary(profile: Annotated[AuthProfile, Depends(check_auth)]) -> dict:
    """Сводка личного графа. Пустой граф — это НЕ ошибка: у нового пользователя его нет."""
    client = GraphifyClient()
    if not client.enabled:
        return {"enabled": False, "exists": False}
    summary = await client.summary(graph_id=_graph_id(profile))
    return {"enabled": True, "exists": bool(summary), **summary}


@graph_router.get("/search")
async def search_graph(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    depth: Annotated[int, Query(ge=1, le=5)] = 3,
) -> dict:
    """Ручной поиск из панели — тот же ГИБРИД, что зовёт модель инструментом.

    Именно тот же: если панель искала бы только по графу, а модель — по графу и векторам,
    пользователь видел бы не то, чем на самом деле пользуется ассистент.
    """
    from service.infrastructure.agents_client import sidecar_vector
    from service.settings import config as _config

    passages, relations = await asyncio.gather(
        sidecar_vector.search_best_effort(_config, user_id=str(profile.user_id), query=q),
        GraphifyClient().query(q, graph_id=_graph_id(profile), depth=depth),
    )
    return {"query": q, "passages": passages, "context": relations}


@graph_router.get("/html", response_class=Response)
async def get_graph_html(profile: Annotated[AuthProfile, Depends(check_auth)]) -> Response:
    """Интерактивный граф. Проксируем через бэкенд, а не отдаём ссылку на сайдкар:
    сайдкар живёт в сети `internal` и снаружи недоступен, а доступ обязан быть под auth —
    иначе чужой граф утёк бы по прямому URL."""
    from service.infrastructure.sidecar import SidecarError

    client = GraphifyClient()
    if not client.enabled:
        raise HTTPException(status_code=503, detail="Граф знаний выключен")
    try:
        page = await client.html(graph_id=_graph_id(profile))
    except SidecarError as exc:
        # ⚠️ Раньше здесь ЛЮБОЙ ответ `>=400` становился «граф ещё не построен» —
        # включая 500 и обрыв связи. Пользователь получал совет построить граф на
        # упавший сайдкар и строил бы его заново. Теперь «нет графа» (None ниже)
        # отделено от «сервис сломался» (502).
        raise HTTPException(status_code=502, detail="Сайдкар графа недоступен") from exc
    if page is None:
        raise HTTPException(status_code=404, detail="Граф ещё не построен")
    return Response(content=page, media_type="text/html; charset=utf-8")


@graph_router.delete("/")
async def delete_graph(profile: Annotated[AuthProfile, Depends(check_auth)]) -> dict:
    """Сброс базы знаний: и граф, и векторы.

    Парно и обязательно: снести только граф — значит оставить дословные фрагменты
    документов лежать в Qdrant, то есть пользователь нажал «очистить», а его тексты
    остались доступны поиску. Это было бы прямым обманом.
    """
    from service.infrastructure.agents_client import sidecar_vector
    from service.settings import config as _config

    graph_ok, vectors_ok = await asyncio.gather(
        GraphifyClient().delete(graph_id=_graph_id(profile)),
        sidecar_vector.delete_user_documents_strict(_config, user_id=str(profile.user_id)),
    )
    return {"deleted": bool(graph_ok or vectors_ok), "graph": graph_ok, "vectors": vectors_ok}
