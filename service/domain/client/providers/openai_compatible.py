"""Общая реализация OpenAI-совместимых провайдер-клиентов.

openai/openrouter/routerai/mws-модули — байт-в-байт одинаковые обёртки над
``AsyncOpenAI``, различаясь лишь base_url/ключом/заголовками/фолбэком. Тела
``create_chat_completion``/``create_completion``/``create_embedding``/нормализации
списка моделей/сборки HTTP-клиента были скопированы в каждый из четырёх — и
расходились (напр. забытый ``set_default_openai_api`` в одном из них). Здесь единый
источник правды; провайдер-модули остаются тонкими шимами, а их module-level API
(``OPENAI_CLIENT``, ``create_chat_completion`` и т.д.) сохранён — фасад/реестр
адресуют их без изменений.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def make_http_client(proxy_name: str, timeout: float) -> httpx.AsyncClient:
    """HTTP-клиент с опциональным per-provider прокси (AGENTS__PROXY_PROVIDERS)."""
    from service.domain.client.providers._http import build_proxy_url

    proxy_url = build_proxy_url(proxy_name)
    try:
        if proxy_url:
            return httpx.AsyncClient(proxy=proxy_url, timeout=timeout)
        return httpx.AsyncClient(timeout=timeout)
    except Exception:
        logger.error("provider HTTP client build failed code=tls_config")
        return httpx.AsyncClient(timeout=timeout)


def normalize_model_list(raw_items: Any) -> list[str]:
    """Уникальные непустые id моделей, отсортированные (dict- и attr-элементы)."""
    model_ids: set[str] = set()
    for item in raw_items or []:
        mid = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
        if isinstance(mid, str) and mid.strip():
            model_ids.add(mid.strip())
    return sorted(model_ids)


async def chat_completion(
    target_client: Any,
    provider_label: str,
    *,
    messages: list[dict[str, str]],
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    n: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    extra: dict[str, Any] | None = None,
):
    """Единое тело chat/completions для OpenAI-совместимых провайдеров."""
    if target_client is None:
        raise RuntimeError(f"{provider_label} client is not configured")

    payload: dict[str, Any] = {"model": model, "messages": messages}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if n is not None:
        payload["n"] = n
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty
    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty
    if extra:
        payload.update(extra)  # tools/tool_choice/response_format/top_p/stop/seed/...

    return await target_client.chat.completions.create(**payload)


async def completion(
    target_client: Any,
    provider_label: str,
    *,
    prompt: str,
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    stop: list[str] | None = None,
):
    """Единое тело /completions для OpenAI-совместимых провайдеров."""
    if target_client is None:
        raise RuntimeError(f"{provider_label} client is not configured")

    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if top_p is not None:
        payload["top_p"] = top_p
    if frequency_penalty is not None:
        payload["frequency_penalty"] = frequency_penalty
    if presence_penalty is not None:
        payload["presence_penalty"] = presence_penalty
    if stop is not None:
        payload["stop"] = stop

    return await target_client.completions.create(**payload)


async def embedding(target_client: Any, provider_label: str, *, text: str, model: str):
    """Единое тело /embeddings для OpenAI-совместимых провайдеров."""
    if target_client is None:
        raise RuntimeError(f"{provider_label} client is not configured")
    return await target_client.embeddings.create(model=model, input=text)
