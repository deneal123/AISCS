"""Служебные модели памяти: общий допуск провайдеров и явное пространство векторов."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time

from service.domain.client.providers.embedding_responses import normalize
from service.domain.client.providers.management.operations import ProviderOperation

CHAT_MODEL = "gpthub-memory"
EMBEDDING_MODEL = "gpthub-memory-embedding"
TEXT_TIMEOUT_SEC = 25
EMBEDDING_TIMEOUT_SEC = 12
_COOLDOWN: dict[tuple[str, str], float] = {}
_TEXT_PREFERENCES = (
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-5-mini",
    "GigaChat-3-Lightning",
    "GigaChat-2",
)


def _text_picker(models, prefer):
    for hint in _TEXT_PREFERENCES:
        for model in models:
            if model == hint or model.endswith("/" + hint):
                return model
    return models[0] if models else None


def chat_model(execution) -> tuple[str, str]:
    admission = execution.provider_admission
    if admission is None:
        raise RuntimeError("memory_admission_unavailable")
    for provider in admission.snapshot.provider_order:
        decision = admission.admit(
            provider, operation=ProviderOperation.CHAT, pick_model=_text_picker
        )
        if decision.admitted and _COOLDOWN.get((provider, decision.model), 0) <= time.monotonic():
            return decision.provider, decision.model
    raise RuntimeError("memory_model_unavailable")


async def complete(payload, execution):
    from service.domain.client import create_chat_completion
    from service.domain.client.providers.image_transport_privacy import private_image_transport
    from service.domain.execution.model import invoke_model_call
    from service.shared.agent_settings import use_settings

    extra = {key: value for key, value in payload.items() if key not in {"model", "stream"}}
    for _ in range(3):
        provider, model = chat_model(execution)
        try:
            with use_settings({"llm_retry_attempts": 1}), private_image_transport():
                return await invoke_model_call(
                    create_chat_completion,
                    model=model,
                    kind=None,
                    execution=execution,
                    provider=provider,
                    pin_provider=provider,
                    **extra,
                )
        except asyncio.CancelledError:
            _COOLDOWN[(provider, model)] = time.monotonic() + 90
            raise
        except Exception as exc:
            _COOLDOWN[(provider, model)] = time.monotonic() + 90
            # Только явный отказ до выполнения допускает резерв в этом же запросе.
            if not _rejected_before_execution(exc):
                raise RuntimeError("memory_model_call_failed") from None
    raise RuntimeError("memory_model_unavailable")


def _rejected_before_execution(exc):
    return getattr(exc, "status_code", None) in {401, 403, 404, 429}


def profile(execution, preferred):
    admission = execution.provider_admission
    if admission is None:
        raise RuntimeError("memory_admission_unavailable")
    chat = []
    for provider in admission.snapshot.provider_order:
        decision = admission.admit(
            provider, operation=ProviderOperation.CHAT, pick_model=_text_picker
        )
        if decision.admitted:
            chat.append({"provider": provider, "model": decision.model})
    embedding = [
        {"provider": item.provider, "model": item.model, "dimension": item.embedding_dimension}
        for item in _candidates(admission, preferred)
    ]
    return {"chat": chat, "embedding": embedding}


def _candidates(admission, preferred):
    provider, _, model = str(preferred or "").partition(":")
    order = list(admission.snapshot.provider_order)
    if provider in order:
        order.remove(provider)
        order.insert(0, provider)
    now = time.monotonic()
    for name in order:
        records = list(admission.snapshot.records.get(name, ()))
        records.sort(key=lambda item: (item.model_id != model, item.embedding_dimension != 1536))
        for record in records:
            if not record.embedding_dimension or not record.supports("embeddings"):
                continue
            if _COOLDOWN.get((name, record.model_id), 0) > now:
                continue
            decision = admission.admit(
                name,
                operation=ProviderOperation.EMBEDDINGS,
                prefer=record.model_id,
                expected_embedding_dimension=record.embedding_dimension,
                pick_model=lambda models, prefer: prefer if prefer in models else None,
            )
            if decision.admitted and decision.client is not None:
                yield decision


async def embed(payload, execution, *, preferred: str):
    admission = execution.provider_admission
    if admission is None:
        raise RuntimeError("memory_admission_unavailable")
    call = {key: value for key, value in payload.items() if key not in {"model", "dimensions"}}
    call["encoding_format"] = "float"
    for _ in range(3):
        decision = next(_candidates(admission, preferred), None)
        if decision is None:
            raise RuntimeError("memory_embedder_unavailable")
        try:
            client = decision.client.with_options(max_retries=0, timeout=12)
            from service.domain.client.providers.image_transport_privacy import (
                private_image_transport,
            )

            with private_image_transport():
                response = await client.embeddings.create(model=decision.model, **call)
            break
        except asyncio.CancelledError:
            _COOLDOWN[(decision.provider, decision.model)] = time.monotonic() + 90
            raise
        except Exception as exc:
            _COOLDOWN[(decision.provider, decision.model)] = time.monotonic() + 90
            if not _rejected_before_execution(exc):
                raise RuntimeError("memory_embedding_call_failed") from None
    else:
        raise RuntimeError("memory_embedder_unavailable")
    data = normalize(decision.provider, response).model_dump()
    inputs = payload.get("input")
    count = 1 if isinstance(inputs, str) else len(inputs or ())
    vectors = data.get("data") or []
    dimension = decision.embedding_dimension
    if len(vectors) != count or not vectors:
        raise RuntimeError("memory_embedding_count_mismatch")
    if sorted(item.get("index", -1) for item in vectors) != list(range(count)):
        raise RuntimeError("memory_embedding_index_mismatch")
    if any(
        not isinstance(item.get("embedding"), list)
        or len(item["embedding"]) != dimension
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in item["embedding"])
        for item in vectors
    ):
        raise RuntimeError("memory_embedding_dimension_mismatch")
    identity = f"{decision.provider}:{decision.model}:{dimension}"
    data.update(
        model=f"{decision.provider}:{decision.model}",
        gpthub_embedding_space=hashlib.sha256(identity.encode()).hexdigest()[:32],
        gpthub_embedding_dimension=dimension,
    )
    return data
