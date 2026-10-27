"""Локальный CPU-сайдкар: общий транспорт и ledger, без отдельного agent loop."""

from typing import Any

from openai import AsyncOpenAI

from service.domain.client.protocol.capabilities import ProviderToolCapabilities

from .runtime import ProviderRuntime, module_getattr
from .spec import ProviderSpec

MODEL_ID = "qwen2.5-1.5b-instruct"
SPEC = ProviderSpec(
    name="local",
    label="Локальная модель",
    default_base_url="http://local-llm:8080/v1",
    api_key_field="local_api_key",
    base_url_field="local_base_url",
    timeout_field="local_timeout_sec",
    ttl_field="local_models_cache_ttl_sec",
    default_timeout_sec=330,
    auto_select_priority=90,
    supports_stream_usage=True,
    fallback_models=(MODEL_ID,),
    fallback_model_capabilities=((MODEL_ID, ("chat", "tools")),),
    require_declared_model_capabilities=True,
    # Нативный tools API Qwen проверяется gateway по исходным схемам аргументов.
    # Один вызов на раунд сохраняет адресуемость эффектов и CPU-профиль.
    tool_capabilities=ProviderToolCapabilities(
        max_calls_per_round=1,
        supports_parallel_calls=False,
    ),
)
PROVIDER_NAME = SPEC.name
_RUNTIME = ProviderRuntime(SPEC)
__getattr__ = module_getattr(_RUNTIME)


def rebuild_client() -> AsyncOpenAI | None:
    """Использовать существующую смену generation после замены ключа."""
    return _RUNTIME.rebuild()


def get_openai_client() -> AsyncOpenAI | None:
    return _RUNTIME.client


async def list_available_models(
    client: AsyncOpenAI | None = None, force_refresh: bool = False
) -> list[str]:
    return await _RUNTIME.list_available_models(client=client, force_refresh=force_refresh)


async def create_chat_completion(
    messages: list[dict[str, Any]],
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


def clear_models_cache() -> None:
    _RUNTIME.models.clear()


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


async def create_embedding(text: str, model: str, *, client=None):
    # Наличие общего метода не объявляет embedding capability у текстовой модели.
    return await _RUNTIME.embedding(client, text=text, model=model)
