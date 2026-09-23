"""OpenRouter client — обвязка собирается фабрикой по спеке.

Провайдер-специфичного тут ровно две вещи: заголовки атрибуции, которых требует
OpenRouter, и `fetch_balance` — он ЕДИНСТВЕННЫЙ наш провайдер с честным
balance-эндпоинтом. Всё остальное (резолв ключа и базы, создание клиента, пересборка,
кэш моделей) живёт в `provider_runtime` и одинаково у всех OpenAI-совместимых.

⚠️ Состояние (`OPENAI_CLIENT`, `OPENAI_API_KEY`, `BASE_URL`) отдаётся через
`__getattr__` модуля и потому ВСЕГДА живое — после замены ключа в админке читатели
видят новый клиент без всяких `global`.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

from .runtime import ProviderRuntime, module_getattr
from .spec import ProviderSpec

logger = logging.getLogger(__name__)

SPEC = ProviderSpec(
    name="openrouter",
    label="OpenRouter",
    default_base_url="https://openrouter.ai/api/v1",
    supports_stream_usage=True,
    auto_select_priority=30,
    api_key_field="openrouter_api_key",
    base_url_field="openrouter_base_url",
    timeout_field="openrouter_timeout_sec",
    ttl_field="openrouter_models_cache_ttl_sec",
    fallback_models=(
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "deepseek/deepseek-chat",
    ),
    fallback_model_capabilities=(
        ("openai/gpt-4o-mini", ("chat", "tools", "vision")),
        ("openai/gpt-4o", ("chat", "tools", "vision")),
        ("deepseek/deepseek-chat", ("chat", "tools")),
    ),
    known_model_capabilities=(
        ("google/gemini-2.5-flash-image", ("chat", "vision", "image_output")),
        ("google/gemini-3.1-flash-image", ("chat", "vision", "image_output")),
        ("google/gemini-3-pro-image", ("chat", "vision", "image_output")),
        ("openai/text-embedding-3-small", ("embeddings",)),
    ),
    embedding_dimensions=(("openai/text-embedding-3-small", 1536),),
    # OpenRouter требует атрибуцию — без этих заголовков он режет лимиты.
    default_headers=(
        ("HTTP-Referer", "https://gpthub.app"),
        ("X-Title", "GPTHub"),
    ),
)

PROVIDER_NAME = SPEC.name
_RUNTIME = ProviderRuntime(SPEC)
__getattr__ = module_getattr(_RUNTIME)


def _resolve_api_key() -> str:
    return _RUNTIME.resolve_api_key()


def _make_http_client() -> httpx.AsyncClient:
    return _RUNTIME.make_http_client()


async def fetch_balance() -> dict | None:
    """Остаток по ключу OpenRouter: {limit, usage, remaining, is_free_tier}.

    OpenRouter — ЕДИНСТВЕННЫЙ наш провайдер с честным balance-эндпоинтом (`/api/v1/key`).
    У OpenAI он закрыт для API-ключей (403 «нужен session-key»), у GigaChat требует
    корп-scope, у MWS/RouterAI его нет вовсе. Именно этот остаток (`remaining=0`)
    предсказал бы аварию «Key limit exceeded». None → ключа нет или эндпоинт не ответил.
    """
    api_key = _resolve_api_key()
    if not api_key:
        return None
    try:
        async with _make_http_client() as client:
            resp = await client.get(
                f"{_RUNTIME.base_url.rstrip('/')}/key",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", {})
        limit = data.get("limit")
        usage = data.get("usage")
        remaining = data.get("limit_remaining")
        # limit=None у OpenRouter означает безлимитный ключ — так и покажем.
        if remaining is None and limit is not None and usage is not None:
            remaining = limit - usage
        return {
            "limit": limit,
            "usage": usage,
            "remaining": remaining,
            "is_free_tier": data.get("is_free_tier"),
            "currency": "USD",
        }
    except Exception:  # noqa: BLE001 - баланс необязателен, панель не должна падать
        logger.debug("provider balance unavailable", extra={"failure_code": "unavailable"})
        return None


def rebuild_client() -> AsyncOpenAI | None:
    """Пересобрать клиента после замены ключа (credentials.set_override)."""
    return _RUNTIME.rebuild()


def get_openai_client() -> AsyncOpenAI | None:
    return _RUNTIME.client


async def list_available_models(
    client: AsyncOpenAI | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """List models from the OpenRouter API (cached, MWS-compatible signature)."""
    return await _RUNTIME.list_available_models(client=client, force_refresh=force_refresh)


async def create_chat_completion(
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    n: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    client: AsyncOpenAI | None = None,
    **extra: Any,
):
    """Call OpenRouter chat completions endpoint (/v1/chat/completions)."""
    return await _RUNTIME.chat_completion(
        client,
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        n=n,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        extra=extra,
    )


async def create_completion(
    prompt: str,
    model: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    stop: list[str] | None = None,
    client: AsyncOpenAI | None = None,
):
    """Call OpenRouter completions endpoint (/v1/completions)."""
    return await _RUNTIME.completion(
        client,
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        frequency_penalty=frequency_penalty,
        presence_penalty=presence_penalty,
        stop=stop,
    )


async def create_embedding(
    text: str,
    model: str,
    *,
    client: AsyncOpenAI | None = None,
):
    """Call OpenRouter embeddings endpoint (/v1/embeddings)."""
    return await _RUNTIME.embedding(client, text=text, model=model)


def clear_models_cache() -> None:
    _RUNTIME.models.clear()
