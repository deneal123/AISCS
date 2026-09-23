"""RouterAI client — обвязка собирается фабрикой по спеке.

RouterAI — OpenAI-совместимый роутер. Своего у него ровно два: заголовок
атрибуции и статический фолбэк моделей. ⚠️ Фолбэк не косметика: `/models` у
RouterAI (300+ моделей) периодически висит, и без него роутинг оставался бы с
пустым списком — агент уходил бы в дефолт `mws-gpt-alpha`, которого у RouterAI
нет, то есть в 400 и мёртвый чат.

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
    name="routerai",
    label="RouterAI",
    default_base_url="https://routerai.ru/api/v1",
    supports_stream_usage=True,
    auto_select_priority=40,
    api_key_field="routerai_api_key",
    base_url_field="routerai_base_url",
    timeout_field="routerai_timeout_sec",
    ttl_field="routerai_models_cache_ttl_sec",
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
    default_headers=(("X-Title", "GPTHub"),),
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
