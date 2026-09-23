"""OpenAI-совместимый шлюз поверх нашего мульти-провайдерного LLM-слоя.

Даёт внешним OpenAI-клиентам (в частности LDR / local-deep-research) доступ к
ЛЮБОМУ нашему провайдеру (openrouter/gigachat/mws/routerai/openai) с нашим
failover и корректной аутентификацией (GigaChat OAuth/TLS) — через один endpoint.

Маршрутизация провайдера — по префиксу модели ``"<provider>:<model>"``
(напр. ``"gigachat:GigaChat-2-Max"``, ``"openrouter:openai/gpt-4o-mini"``,
``"mws:mws-gpt-alpha"``). Без известного префикса — активный провайдер + failover.

Шлюз НЕ тарифицирует: это сырой LLM-прокси (биллинг LDR идёт через его /metrics,
единый источник). Внутренний (docker-сеть); авторизация — bearer-ключ
``AGENTS__LLM_GATEWAY_API_KEY`` (если пуст — пускаем, dev-режим на внутренней сети).
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from service.domain.client import (
    create_chat_completion,
    initialize_run_provider_admission,
    list_available_models,
)
from service.domain.client.provider_operations import ProviderOperation
from service.domain.client.registry import PROVIDER_MODULES
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.settings import config

v1_router = APIRouter(prefix="/v1")

_KNOWN_PROVIDERS = set(PROVIDER_MODULES.keys())


@asynccontextmanager
async def _gateway_execution():
    """Lease one immutable provider snapshot for the complete gateway request."""

    with use_run_execution(PrivateRunResources()) as execution:
        await initialize_run_provider_admission(execution)
        yield execution


def _auth(authorization: str | None) -> None:
    if not getattr(config.agents, "llm_gateway_enabled", False):
        raise HTTPException(status_code=404, detail="gateway disabled")
    key = (getattr(config.agents, "llm_gateway_api_key", "") or "").strip()
    if not key:
        return  # ключ не задан → внутренний dev-режим
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != key:
        raise HTTPException(status_code=401, detail="invalid gateway api key")


def _split_model(model: str) -> tuple[str | None, str]:
    """``"<provider>:<model>"`` → (provider, model); иначе (None, model)."""
    if isinstance(model, str) and ":" in model:
        prov, _, rest = model.partition(":")
        if prov.lower() in _KNOWN_PROVIDERS and rest:
            return prov.lower(), rest
    return None, model


async def _complete(payload: dict):
    """Не-стримовый вызов через наш мульти-провайдерный фасад (failover/retry/
    circuit-breaker) с ПОЛНЫМ пробросом OpenAI-полей (tools/tool_choice/
    response_format/… — критично для агентных стратегий LDR). Провайдер по
    префиксу модели (пин), иначе активный. Стрим буферим сами → всегда non-stream.
    """
    provider, real_model = _split_model(payload.get("model") or "")
    messages = payload.get("messages") or []
    extra = {k: v for k, v in payload.items() if k not in ("stream", "model", "messages")}
    return await create_chat_completion(messages, real_model, provider=provider, **extra)


def _chunk(base: dict, delta: dict, finish: str | None) -> str:
    obj = dict(base)
    obj["choices"] = [{"index": 0, "delta": delta, "finish_reason": finish}]
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@v1_router.post("/chat/completions")
async def chat_completions(payload: dict, authorization: str | None = Header(None)):
    _auth(authorization)
    model = payload.get("model") or ""
    stream = bool(payload.get("stream"))

    try:
        async with _gateway_execution():
            resp = await _complete(payload)
    except Exception:  # вернём OpenAI-подобную ошибку (LangChain её понимает)
        return JSONResponse(
            status_code=502,
            content={"error": {"message": "upstream_error", "type": "upstream_error"}},
        )

    if not stream:
        # Возвращаем ответ как есть: resp.model = РЕАЛЬНАЯ модель провайдера
        # (без префикса) — так метрики LDR совпадут с нашим прайс-реестром.
        return resp.model_dump() if hasattr(resp, "model_dump") else resp

    # stream=true → буферизованный SSE одним контент-чанком из полного ответа
    # (провайдер-форс не поддерживает истинный per-token стрим; для LDR это ок).
    choice = resp.choices[0]
    content = getattr(getattr(choice, "message", None), "content", "") or ""
    finish = getattr(choice, "finish_reason", "stop") or "stop"
    base = {
        "id": getattr(resp, "id", "chatcmpl-gw"),
        "object": "chat.completion.chunk",
        "created": getattr(resp, "created", int(time.time())),
        "model": getattr(resp, "model", model),
    }
    usage = None
    u = getattr(resp, "usage", None)
    if u is not None:
        usage = {
            "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens": getattr(u, "total_tokens", 0) or 0,
        }

    def _sse():
        yield _chunk(base, {"role": "assistant"}, None)
        if content:
            yield _chunk(base, {"content": content}, None)
        final = dict(base)
        final["choices"] = [{"index": 0, "delta": {}, "finish_reason": finish}]
        if usage is not None:
            final["usage"] = usage
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_sse(), media_type="text/event-stream")


@v1_router.get("/models")
async def models(authorization: str | None = Header(None)):
    _auth(authorization)
    try:
        ids = await list_available_models()
    except Exception:
        ids = []
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "owned_by": "gpthub"} for m in ids],
    }


async def _embed(payload: dict, execution):
    """Эмбеддинги через наш мульти-провайдерный слой. Провайдер по префиксу модели,
    иначе активный; его настроенный OPENAI_CLIENT (base_url/ключ/TLS). БЕЗ failover:
    размерность вектора обязана быть стабильной (иначе порча коллекции Qdrant у
    MemOS) — при неверном пине лучше явная 502, чем тихая смена размерности.
    """
    provider, real_model = _split_model(payload.get("model") or "")
    admission = execution.provider_admission
    if admission is None:
        raise RuntimeError("provider admission unavailable")
    expected_dimension = payload.get("dimensions")
    if expected_dimension is not None:
        expected_dimension = int(expected_dimension)
    if provider:
        decision = admission.admit(
            provider,
            operation=ProviderOperation.EMBEDDINGS,
            prefer=real_model,
            expected_embedding_dimension=expected_dimension,
            pick_model=lambda models, prefer: (
                prefer if prefer in models else models[0] if models else None
            ),
        )
    else:
        decision = admission.admit_first(
            operation=ProviderOperation.EMBEDDINGS,
            prefer=real_model,
            expected_embedding_dimension=expected_dimension,
            pick_model=lambda models, prefer: (
                prefer if prefer in models else models[0] if models else None
            ),
        )
    if decision is None or not decision.admitted or decision.client is None:
        raise RuntimeError("embedding operation unsupported")
    # input может быть str или list[str] — SDK принимает оба; пробрасываем
    # dimensions/encoding_format/user, если заданы.
    call = {k: v for k, v in payload.items() if k != "model"}
    call["model"] = decision.model
    response = await decision.client.embeddings.create(**call)
    dimension = expected_dimension or decision.embedding_dimension
    if dimension is not None:
        vectors = [getattr(item, "embedding", ()) for item in getattr(response, "data", ())]
        if not vectors or any(len(vector) != dimension for vector in vectors):
            raise RuntimeError("embedding dimension mismatch")
    return response


@v1_router.post("/embeddings")
async def embeddings(payload: dict, authorization: str | None = Header(None)):
    _auth(authorization)
    try:
        async with _gateway_execution() as execution:
            resp = await _embed(payload, execution)
    except Exception:  # OpenAI-подобная ошибка
        return JSONResponse(
            status_code=502,
            content={"error": {"message": "upstream_error", "type": "upstream_error"}},
        )
    return resp.model_dump() if hasattr(resp, "model_dump") else resp
