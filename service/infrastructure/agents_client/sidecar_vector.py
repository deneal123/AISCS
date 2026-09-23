"""Клиент к ``/vector/*`` сайдкара agents (Фаза 3).

Векторное хранилище считает эмбеддинги через мультипровайдерный слой, которым владеет
сайдкар, — туда и переезжают индексация/поиск/снос. Backend (upload, graph_api) остаётся
клиентом: иначе в Фазе 5, когда домен уедет, эти ручки останутся с битым импортом.

Локального пути БОЛЬШЕ НЕТ: домен уехал в сайдкар, backend физически не может исполнить
хранилище. Низкоуровневые функции по-прежнему возвращают ``None`` при сбое связи, а
обёртки ниже переводят это в ПОЛЬЗОВАТЕЛЬСКУЮ семантику каждой операции — ту же, что
была у локального ``vector_store``: индексация и поиск best-effort, снос — строгий.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from service.infrastructure.sidecar import (  # noqa: E402
    SidecarBadRequest,
    SidecarClient,
    SidecarError,
)

# Индексация режет документ на чанки и считает эмбеддинги — это дольше поиска.
INDEX_TIMEOUT_SEC = 120.0
QUERY_TIMEOUT_SEC = 30.0


def _base(config: Any) -> str:
    return str(getattr(getattr(config, "agents", None), "sidecar_url", "") or "").rstrip("/")


def _client(config: Any, timeout: float) -> SidecarClient:
    agents_cfg = getattr(config, "agents", None)
    return SidecarClient(
        service="agents",
        base_url=str(getattr(agents_cfg, "sidecar_url", "") or ""),
        timeout=timeout,
        api_key=str(getattr(agents_cfg, "llm_gateway_api_key", "") or ""),
    )


async def _post(config: Any, path: str, payload: dict, *, timeout: float) -> dict | None:
    """POST на сайдкар. `None` = не смогли; вызывающий деградирует САМ.

    ⚠️ Fail-open здесь сохранён осознанно: вектора — обогащение ответа, а не сам ответ.
    Но он теперь ЯВНЫЙ, а не встроен в транспорт: отличаются «нас отвергли» (4xx, наша
    вина — стоит увидеть в логах отдельно) и «сервис лёг» (5xx/сеть).
    """
    try:
        return await _client(config, timeout).request_json("POST", path, json_body=payload)
    except SidecarBadRequest as exc:
        logger.info(
            "agents integration failure",
            extra={"component": "vector", "failure_code": exc.code},
        )
        return None
    except SidecarError:
        logger.warning(
            "agents integration failure",
            extra={"component": "vector", "failure_code": "unavailable"},
        )
        return None


async def index_document(config: Any, *, user_id: str, filename: str, text: str) -> int | None:
    """Проиндексировать документ. ``None`` = не смогли достучаться."""
    data = await _post(
        config,
        "/vector/index",
        {"user_id": user_id, "filename": filename, "text": text},
        timeout=INDEX_TIMEOUT_SEC,
    )
    if data is None:
        return None
    chunks = data.get("chunks")
    return int(chunks) if isinstance(chunks, int) else None


async def search(
    config: Any, *, user_id: str, query: str, top_k: int | None = None
) -> list[dict] | None:
    """Поиск фрагментов. ``None`` = не смогли достучаться."""
    data = await _post(
        config,
        "/vector/search",
        {"user_id": user_id, "query": query, "top_k": top_k},
        timeout=QUERY_TIMEOUT_SEC,
    )
    if data is None:
        return None
    passages = data.get("passages")
    return passages if isinstance(passages, list) else None


async def delete_user_documents(config: Any, *, user_id: str) -> bool | None:
    """Снести документы пользователя. ``None`` = не смогли достучаться.

    Отличать ``None`` от ``False`` обязательно: ``False`` — «сходили, сносить было
    нечего», ``None`` — «не сходили вовсе». Спутать их значит оставить тексты
    пользователя в Qdrant после нажатия «очистить».
    """
    data = await _post(config, "/vector/delete", {"user_id": user_id}, timeout=QUERY_TIMEOUT_SEC)
    if data is None:
        return None
    return bool(data.get("deleted"))


# --------------------------------------------------------------------------- фасад --
# Локального фолбэка БОЛЬШЕ НЕТ: домен уехал в сайдкар, и backend физически не может
# исполнить хранилище. Поэтому сохраняем не «запасной путь», а ПОЛЬЗОВАТЕЛЬСКУЮ семантику
# каждой операции — ровно ту, что была у локального vector_store.


async def index_document_best_effort(config: Any, *, user_id: str, filename: str, text: str) -> int:
    """Проиндексировать документ. Недоступен сайдкар → 0 и ERROR, но НЕ исключение.

    Индексация всегда была best-effort: она идёт параллельно с построением графа, и её
    сбой не должен ронять саму загрузку файла (пользователь потеряет документ из-за
    неработающего поиска — несоразмерно).
    """
    chunks = await index_document(config, user_id=user_id, filename=filename, text=text)
    if chunks is None:
        logger.error("документ НЕ проиндексирован: сайдкар недоступен (поиск по нему не найдёт)")
        return 0
    return chunks


async def search_best_effort(
    config: Any, *, user_id: str, query: str, top_k: int | None = None
) -> list[dict]:
    """Поиск фрагментов. Недоступен сайдкар → пусто, как при «ничего не нашлось».

    Так вело себя и локальное хранилище (fail-open): отсутствие контекста для ответа —
    не ошибка, ассистент отвечает без него.
    """
    passages = await search(config, user_id=user_id, query=query, top_k=top_k)
    if passages is None:
        logger.error("поиск по документам не выполнен: сайдкар недоступен")
        return []
    return passages


async def delete_user_documents_strict(config: Any, *, user_id: str) -> bool:
    """Снести документы пользователя. Недоступен сайдкар → False, и это ВАЖНО.

    Здесь fail-open недопустим: сказать «удалено», не удалив, — прямой обман. Вызывающий
    обязан показать неуспех пользователю, а не проглотить его.
    """
    deleted = await delete_user_documents(config, user_id=user_id)
    if deleted is None:
        logger.error(
            "документы НЕ снесены: сайдкар недоступен — пользователю нельзя "
            "сообщать об успешной очистке"
        )
        return False
    return deleted
