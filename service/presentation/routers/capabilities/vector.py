"""`/vector/*` — векторное хранилище документов пользователя (Qdrant).

Индексация переехала сюда вместе с провайдерами: эмбеддинги считает мультипровайдерный
слой, которым владеет сайдкар. Backend остаётся клиентом.
"""

from __future__ import annotations

from fastapi import APIRouter, Header

from service.presentation import runtime
from service.presentation.deps import internal_auth
from service.presentation.errors import error
from service.schemas.vector import (
    VectorDeleteRequest,
    VectorIndexRequest,
    VectorSearchRequest,
)

router = APIRouter(prefix="/vector")

_UNAVAILABLE = error("vector_unavailable", "векторное хранилище недоступно", 503)


@router.post("/index")
async def index(
    payload: VectorIndexRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Проиндексировать документ пользователя (нарезка + эмбеддинги + запись в Qdrant)."""
    # ⚠️ Ключ проверяется ПЕРВЫМ. Раньше проверка стояла после загрузки движка (у
    # `/vector/*` — после проверки хранилища), и неавторизованный запрос успевал
    # узнать, поднят ли сервис: 503 и 401 различимы снаружи.
    internal_auth(authorization)
    store = runtime.vector_store()
    if store is None:
        return _UNAVAILABLE
    chunks = await store.index_document(
        user_id=payload.user_id, filename=payload.filename, text=payload.text
    )
    return {"chunks": int(chunks or 0)}


@router.post("/search")
async def search(
    payload: VectorSearchRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Поиск дословных фрагментов по документам пользователя."""
    internal_auth(authorization)
    store = runtime.vector_store()
    if store is None:
        return _UNAVAILABLE
    kwargs = {"user_id": payload.user_id, "query": payload.query}
    if payload.top_k is not None:
        kwargs["top_k"] = payload.top_k
    return {"passages": await store.search(**kwargs)}


@router.post("/delete")
async def delete(
    payload: VectorDeleteRequest, authorization: str | None = Header(default=None)
) -> dict:
    """Снести все векторные документы пользователя (кнопка «очистить» в панели).

    Парно к сносу графа: оставить фрагменты в Qdrant после «очистить» — прямой обман
    пользователя, поэтому вызывающий обязан звать обе операции.
    """
    internal_auth(authorization)
    store = runtime.vector_store()
    if store is None:
        return _UNAVAILABLE
    return {"deleted": bool(await store.delete_user_documents(user_id=payload.user_id))}
