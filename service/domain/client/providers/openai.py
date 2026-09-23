"""Нативный OpenAI client — обвязка собирается фабрикой по спеке.

⚠️ ЕДИНСТВЕННЫЙ провайдер, которому НЕ переключают Agents SDK на
chat/completions: Responses API есть только у него. Остальные отвечают на
`/responses` 404 (у OpenRouter — HTML), и агенты уходили бы в фолбэк.

Своей базы у него обычно нет — тогда SDK берёт собственный дефолт. Своих
настроек таймаута и TTL тоже нет, отсюда константы в спеке.

⚠️ Состояние (`OPENAI_CLIENT`, `OPENAI_API_KEY`, `BASE_URL`) отдаётся через `__getattr__`
модуля и потому ВСЕГДА живое: после замены ключа в админке читатели видят новый клиент,
и никакого `global` для этого не нужно.
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI

from .runtime import ProviderRuntime, module_getattr
from .spec import ProviderSpec

SPEC = ProviderSpec(
    name="openai",
    label="OpenAI",
    default_base_url="",
    base_url_suffix=None,
    supports_stream_usage=True,
    auto_select_priority=20,
    auto_select_fields=("openai_api_key", "openai_base_url"),
    api_key_field="openai_api_key",
    base_url_field="openai_base_url",
    default_timeout_sec=60.0,
    fallback_models=("gpt-4o-mini", "gpt-4o"),
    fallback_model_capabilities=(
        ("gpt-4o-mini", ("chat", "tools", "vision")),
        ("gpt-4o", ("chat", "tools", "vision")),
    ),
    known_model_capabilities=(
        ("text-embedding-3-small", ("embeddings",)),
        ("text-embedding-3-large", ("embeddings",)),
        ("text-embedding-ada-002", ("embeddings",)),
        ("whisper-1", ("transcription",)),
        ("gpt-4o-mini-transcribe", ("transcription",)),
        ("gpt-4o-transcribe", ("transcription",)),
    ),
    embedding_dimensions=(
        ("text-embedding-3-small", 1536),
        ("text-embedding-3-large", 3072),
        ("text-embedding-ada-002", 1536),
    ),
    force_chat_completions_api=False,
)


PROVIDER_NAME = SPEC.name
_RUNTIME = ProviderRuntime(SPEC)
__getattr__ = module_getattr(_RUNTIME)


def rebuild_client() -> AsyncOpenAI | None:
    """Пересобрать клиента после замены ключа (credentials.set_override)."""
    return _RUNTIME.rebuild()


def get_openai_client() -> AsyncOpenAI | None:
    return _RUNTIME.client


async def list_available_models(
    client: AsyncOpenAI | None = None,
    force_refresh: bool = False,
) -> list[str]:
    """Список моделей провайдера (кэшируется)."""
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
    """Вызов chat/completions."""
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
    """Вызов /completions."""
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
    """Вызов /embeddings."""
    return await _RUNTIME.embedding(client, text=text, model=model)


def clear_models_cache() -> None:
    _RUNTIME.models.clear()
