"""Векторный поиск по документам пользователя — вторая половина гибридного поиска.

Зачем он рядом с графом, а не вместо: graphify — **не векторный индекс**, это его
собственные слова. Он силён на РЕЛЯЦИОННЫХ вопросах («как X связан с Y», «что завязано
на Z»), потому что обходит рёбра. Но на «найди, что там написано про сроки оплаты» обход
графа слабее эмбеддингов: узел графа — это сущность, а не абзац, и дословный текст в нём
не лежит.

Поэтому: эмбеддинги дают ДОСЛОВНЫЕ фрагменты, граф даёт СВЯЗИ. Модель получает и то, и
другое, помеченными по отдельности, — и сама решает, чем пользоваться.

Qdrant дёргаем по REST через httpx: клиентская библиотека qdrant нам ради четырёх
запросов не нужна.
"""

from __future__ import annotations

import logging
import uuid

import httpx

from service.settings import config
from service.shared.agent_settings import runtime_settings
from service.shared.token_budget import chars_for_tokens

logger = logging.getLogger(__name__)

# Пространство имён для детерминированных id точек: повторная загрузка того же документа
# ПЕРЕЗАПИСЫВАЕТ свои чанки, а не плодит дубликаты.
_POINT_NS = uuid.UUID("6f1d4a3e-6f0e-4f7a-9b1a-6c2f5c9a1d77")


def _collection() -> str:
    return str(config.agents.doc_vector_collection or "gpthub_docs")


def _base() -> str:
    return (config.agents.qdrant_url or "").rstrip("/")


def enabled() -> bool:
    return bool(
        runtime_settings.get_agents("vector_search_enabled", config.agents.vector_search_enabled)
        and _base()
    )


def chunk_text(text: str) -> list[str]:
    """Нарезать документ на перекрывающиеся куски.

    Перекрытие обязательно: без него факт, попавший на стык, не найдётся ни в одном
    чанке целиком. Режем по абзацам, чтобы не рвать предложение посередине.
    """
    # Потолок эмбеддера: чанк не должен превышать его лимит входа (GigaChat: 514
    # токенов, иначе 413 и индексация падает). chars_for_tokens занижает символы, а
    # BPE GigaChat на кириллице плотнее — поэтому режем по консервативному потолку.
    embed_max = int(config.agents.doc_embedder_max_tokens or 480)
    chunk_tokens = min(int(config.agents.doc_chunk_tokens or 700), embed_max)
    size = chars_for_tokens(chunk_tokens)
    overlap = chars_for_tokens(
        min(int(config.agents.doc_chunk_overlap_tokens or 100), chunk_tokens // 3)
    )
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= size:
        return [body]

    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = min(start + size, len(body))
        if end < len(body):
            # Отступаем до ближайшей границы абзаца/строки — но не дальше половины
            # чанка назад, иначе на плотном тексте куски выродятся в крошки.
            window = body.rfind("\n", start + size // 2, end)
            if window != -1:
                end = window
        piece = body[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(body):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _embedder_candidates() -> list[dict]:
    """Основной эмбеддер + фолбэки (в порядке предпочтения). Каждый — {model, dim}."""
    # ⚠️ ОСНОВНОЙ ЭМБЕДДЕР ЧИТАЛСЯ МИМО OVERLAY АДМИНКИ, а фолбэки строкой ниже — через
    # него. Наружу это выглядело абсурдно: админ меняет запасные эмбеддеры и они
    # применяются, меняет ОСНОВНОЙ — и ничего не происходит, без единой ошибки.
    primary = {
        "model": str(
            runtime_settings.get_agents("doc_embedder_model", config.agents.doc_embedder_model)
            or ""
        ),
        "dim": int(
            runtime_settings.get_agents("doc_embedder_dim", config.agents.doc_embedder_dim) or 1536
        ),
    }
    raw = runtime_settings.get_agents("doc_embedder_fallback", config.agents.doc_embedder_fallback)
    fallbacks = [c for c in (raw or []) if isinstance(c, dict) and c.get("model")]
    return [primary] + fallbacks


async def _embed_with_dim(texts: list[str]) -> tuple[list[list[float]], int, bool]:
    """Эмбеддинги с ФЕЙЛОВЕРОМ по эмбеддер-провайдерам.

    → (векторы, dim выбранного эмбеддера, is_primary). ``is_primary`` — True, только
    если сработал ОСНОВНОЙ эмбеддер (первый кандидат), False — если пришлось уйти на
    фолбэк. Это различие критично для индексации: пересоздавать общую коллекцию под
    новый dim можно ТОЛЬКО при смене основного эмбеддера (осознанная миграция), но
    НЕ при транзиентном фолбэке — иначе мигание основного провайдера во время одной
    загрузки стёрло бы векторы ВСЕХ пользователей (коллекция одна на всех).

    Раньше был жёсткий пин к doc_embedder_model без фолбэка: смерть провайдера (напр. GigaChat
    с невалидным TLS) роняла ВЕСЬ vector search. Теперь: заблокированные/выключенные/мёртвые
    провайдеры пропускаются, при ошибке провайдер гасится в circuit_breaker и берётся следующий
    кандидат из doc_embedder_fallback.
    """
    from service.domain.client import circuit_breaker, provider_policy
    from service.domain.client.provider_operations import ProviderOperation
    from service.domain.run_context import current_execution

    execution = current_execution()
    admission = execution.provider_admission if execution is not None else None
    unavailable = set() if admission is not None else await provider_policy.unavailable_providers()
    last_exc: Exception | None = None
    # ⚠️ ПОЧЕМУ КАНДИДАТ НЕ ПРОБОВАН — ОБЯЗАНО БЫТЬ В ЛОГАХ. При молчаливых `continue`
    # мёртвая цепочка выглядела как «эмбеддер сломан»: по следу не понять, что запасной
    # ВООБЩЕ не пробовался, потому что его провайдер выключен.
    skipped: list[str] = []
    for idx, cand in enumerate(_embedder_candidates()):
        model = str(cand.get("model") or "")
        provider, _, real_model = model.partition(":")
        if not real_model:  # без префикса «<provider>:» — активный провайдер
            provider, real_model = "", model
        dim = int(
            cand.get("dim")
            or runtime_settings.get_agents("doc_embedder_dim", config.agents.doc_embedder_dim)
            or 1536
        )
        if provider and provider in unavailable:
            skipped.append(f"{model}: провайдер выключен/заблокирован")
            continue  # мёртв/заблокирован/выключен — не пробуем
        provider_name = provider
        client = None
        if admission is not None:
            provider_name = provider or admission.snapshot.active_provider
            decision = admission.admit(
                provider_name,
                operation=ProviderOperation.EMBEDDINGS,
                prefer=real_model,
                expected_embedding_dimension=dim,
                pick_model=lambda models, prefer: (
                    prefer if prefer in models else models[0] if models else None
                ),
            )
            if decision.admitted:
                client = decision.client
                real_model = decision.model or real_model
        else:
            from service.domain.client.provider_compat import resolve_model_client

            provider_name, client = await resolve_model_client(
                real_model,
                preferred_provider=provider or None,
            )
        if client is None:
            skipped.append(f"{model}: клиент провайдера не настроен")
            continue
        try:
            resp = await client.embeddings.create(model=real_model, input=texts)
            # ⚠️ `resp.usage` НЕ тарифицируется ОСОЗНАННО: эмбеддинг-токены на порядки
            # дешевле чат-токенов, а индексацию покрывает плоская цена graphify
            # (`graph_index_price_rub_per_doc`). Подорожают — протянуть usage в per_call.
            vectors = [list(item.embedding) for item in resp.data]
            if len(vectors) != len(texts) or any(len(vector) != dim for vector in vectors):
                logger.warning("embedding provider failed code=dimension_mismatch")
                continue
            if provider_name:
                await circuit_breaker.clear_down(provider_name)
            # Последний фолбэк размерности. Через overlay, как и основной кандидат:
            # иначе половина настройки слушалась бы админа, а половина нет.
            return vectors, dim, idx == 0
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            from service.domain.client.protocol import classify_provider_failure

            code = classify_provider_failure(exc, provider=provider_name).code.value
            if provider_name and circuit_breaker.should_trip(exc):
                await circuit_breaker.mark_down(provider_name, reason=code)
            logger.warning("embedding provider failed code=%s", code)
            continue

    # Ни один кандидат не сработал. Говорим, ЧТО именно случилось с каждым: без этого
    # «нет доступного эмбеддера» одинаково выглядит и при сбое провайдера, и при пустой
    # цепочке, и при выключенном фолбэке — а чинятся они по-разному.
    if skipped or last_exc:
        logger.error("embedding unavailable code=unavailable")
    from service.domain.integration_failure import (
        IntegrationFailure,
        IntegrationFailureCode,
        IntegrationSource,
    )

    raise IntegrationFailure(
        source=IntegrationSource.PROVIDER,
        code=IntegrationFailureCode.UNAVAILABLE,
        retryable=True,
    ) from None


async def _ensure_collection(
    client: httpx.AsyncClient, dim: int, *, allow_recreate: bool = True
) -> bool:
    """Гарантировать коллекцию размерности dim. → True, если она готова работать с этим
    dim; False, если не готова и пересоздание запрещено.

    allow_recreate=True (путь ИНДЕКСАЦИИ): при смене эмбеддера (другой dim) ПЕРЕСОЗДАЁМ —
    старые векторы несовместимы, а дальше мы всё равно пишем заново.

    allow_recreate=False (путь ПОИСКА): поиск — это ЧТЕНИЕ и деструктивным быть не должен.
    При несовпадении dim или отсутствии коллекции возвращаем False и НЕ трогаем индекс.
    Иначе транзиентный фейловер эмбеддера на другой dim во время поиска сносил бы общий
    индекс ВСЕХ пользователей (коллекция одна на всех) — крит-находка аудита P0.2. Плюс
    при восстановлении основного эмбеддера следующий поиск сносил бы его повторно.
    """
    name = _collection()
    resp = await client.get(f"{_base()}/collections/{name}")
    if resp.status_code == 200:
        size = None
        try:
            params = ((resp.json() or {}).get("result") or {}).get("config", {}).get("params", {})
            vecs = params.get("vectors", {}) if isinstance(params, dict) else {}
            size = vecs.get("size") if isinstance(vecs, dict) else None
        except Exception:  # noqa: BLE001
            size = None
        if size == int(dim):
            return True
        if not allow_recreate:
            logger.warning(
                "Поиск: dim %s не совпал с коллекцией %s (%s) — индекс НЕ трогаю, вернётся []",
                dim,
                name,
                size,
            )
            return False
        logger.warning(
            "Эмбеддер сменил размерность (%s→%s): пересоздаю коллекцию %s (старые векторы стёрты)",
            size,
            dim,
            name,
        )
        await client.delete(f"{_base()}/collections/{name}")
    elif not allow_recreate:
        # Коллекции ещё нет — на пути ЧТЕНИЯ пустую не создаём (нечего искать).
        return False
    await client.put(
        f"{_base()}/collections/{name}",
        json={"vectors": {"size": int(dim), "distance": "Cosine"}},
    )
    return True


async def index_document(*, user_id: str, filename: str, text: str) -> int:
    """Проиндексировать документ. → число записанных чанков (0 при любой неудаче)."""
    if not enabled() or not user_id or not text.strip():
        return 0
    chunks = chunk_text(text)
    if not chunks:
        return 0
    try:
        vectors, dim, is_primary = await _embed_with_dim(chunks)
        points = [
            {
                "id": str(uuid.uuid5(_POINT_NS, f"{user_id}|{filename}|{idx}")),
                "vector": vector,
                "payload": {
                    "user_id": str(user_id),
                    "filename": filename,
                    "chunk": idx,
                    "text": chunk,
                },
            }
            for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=False))
        ]
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Пересоздавать коллекцию под новый dim можно ТОЛЬКО при смене ОСНОВНОГО
            # эмбеддера (осознанная миграция). Коллекция одна на всех: dim от фолбэка —
            # это мигание провайдера, и пересоздание снесло бы векторы ВСЕХ пользователей
            # (аудит P0.2, здесь его write-близнец). Пропускаем запись fail-soft.
            if not await _ensure_collection(client, dim, allow_recreate=is_primary):
                logger.warning(
                    "Индексация пропущена: фолбэк-эмбеддер (dim %s) не совпал с коллекцией — "
                    "общий индекс не пересоздаю, жду восстановления основного эмбеддера",
                    dim,
                )
                return 0
            resp = await client.put(
                f"{_base()}/collections/{_collection()}/points",
                params={"wait": "true"},
                json={"points": points},
            )
            if resp.status_code >= 400:
                logger.warning("qdrant upsert failed status_family=%sxx", resp.status_code // 100)
                return 0
        return len(points)
    except Exception:
        logger.warning("vector indexing failed code=unavailable")
        return 0


async def search(*, user_id: str, query: str, top_k: int | None = None) -> list[dict]:
    """Найти дословные фрагменты документов пользователя. Fail-open: [] при любой беде."""
    if not enabled() or not user_id or not query.strip():
        return []
    # ⚠️ Через overlay, а не из конфига напрямую: ключ ОБЪЯВЛЕН в админке, и чтение
    # мимо снимка означало бы, что админ меняет значение, а поведение прежнее —
    # молча. Ровно этот класс дефекта нашёл офлайн-страж ключей agents.*.
    limit = int(
        top_k
        or runtime_settings.get_agents("doc_vector_top_k", config.agents.doc_vector_top_k)
        or 5
    )
    try:
        vectors, dim, _ = await _embed_with_dim([query])
        vector = vectors[0]
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Поиск НЕ деструктивен: при несовпадении dim (после авто-переключения
            # эмбеддера на другой провайдер) коллекцию НЕ пересоздаём — вернём [] до
            # восстановления/переиндексации. Иначе одно чтение сносило бы общий индекс
            # всех пользователей (аудит P0.2). Fail-open.
            if not await _ensure_collection(client, dim, allow_recreate=False):
                return []
            resp = await client.post(
                f"{_base()}/collections/{_collection()}/points/search",
                json={
                    "vector": vector,
                    "limit": limit,
                    # Фильтр по пользователю — не оптимизация, а изоляция: коллекция одна
                    # на всех, и без него нашлись бы чужие документы.
                    "filter": {"must": [{"key": "user_id", "match": {"value": str(user_id)}}]},
                    "with_payload": True,
                },
            )
        if resp.status_code >= 400:
            logger.warning("qdrant search failed status_family=%sxx", resp.status_code // 100)
            return []
        hits = (resp.json() or {}).get("result") or []
        return [
            {
                "text": (hit.get("payload") or {}).get("text") or "",
                "filename": (hit.get("payload") or {}).get("filename") or "",
                "score": float(hit.get("score") or 0.0),
            }
            for hit in hits
        ]
    except Exception:
        logger.warning("vector search failed code=unavailable")
        return []


async def delete_user_documents(*, user_id: str) -> bool:
    """Стереть векторы пользователя (парно к сбросу графа — иначе он стёр бы половину)."""
    if not enabled() or not user_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_base()}/collections/{_collection()}/points/delete",
                params={"wait": "true"},
                json={"filter": {"must": [{"key": "user_id", "match": {"value": str(user_id)}}]}},
            )
        return resp.status_code < 400
    except Exception:
        logger.warning("vector delete failed code=unavailable")
        return False
