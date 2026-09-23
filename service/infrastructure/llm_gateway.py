"""Клиент backend к OpenAI-совместимому шлюзу сайдкара (`/v1`).

Backend иногда сам нуждается в LLM — например, аналитика памяти извлекает факты из
переписки. Раньше он звал мультипровайдерный слой напрямую (`domain.client
.create_chat_completion`), но провайдерами владеет сайдкар: у него ключи, политика,
circuit breaker и фейловер. Ходить мимо него значит иметь второе мнение о том, кто из
провайдеров жив, — ровно та болезнь, из-за которой мы убрали второй `/v1` из backend.

Поэтому backend становится обычным клиентом шлюза, как memos и ldr. Ключ тот же
(`AGENTS__LLM_GATEWAY_API_KEY`).
"""

from __future__ import annotations

import logging
from typing import Any

from service.infrastructure.sidecar import SidecarClient, SidecarError

logger = logging.getLogger(__name__)

# Вызовы backend'а к LLM — служебные и короткие (извлечение фактов, разметка), поэтому
# таймаут скромный: подвиснуть на минуту здесь хуже, чем не получить результат.
GATEWAY_TIMEOUT_SEC = 60.0


async def chat_completion(
    config: Any,
    *,
    messages: list[dict],
    model: str,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> tuple[str, dict] | None:
    """Один chat-вызов через шлюз. ``(текст, usage)`` либо ``None``, если не смогли.

    ⚠️ ``usage`` возвращается ОБЯЗАТЕЛЬНО, а не отбрасывается ради простоты: вызовы
    backend'а к LLM тарифицируются (извлечение фактов памяти списывается с пользователя
    отдельно). Потеряем токены здесь — работа достанется бесплатно, и заметить это будет
    нечем: ошибки не возникает, просто счёт меньше.
    """
    agents = getattr(config, "agents", None)
    client = SidecarClient(
        service="agents-v1",
        base_url=str(getattr(agents, "sidecar_url", "") or ""),
        timeout=GATEWAY_TIMEOUT_SEC,
        api_key=str(getattr(agents, "llm_gateway_api_key", "") or ""),
    )
    if not client.available:
        return None

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    try:
        # ⚠️ `/v1` отвечает ошибками в ФОРМЕ OPENAI (`{"error": {"message","type"}}`) —
        # это названное исключение в регламенте, чужой протокол. Общая база разберёт
        # такое тело как «код пустой, текст есть»: различить 4xx и 5xx по HTTP-статусу
        # она всё равно может, а код в этом случае просто не заполнится.
        data = await client.request_json("POST", "/v1/chat/completions", json_body=payload)
    except SidecarError:  # служебный вызов: его сбой не должен ронять вызывающего
        logger.warning("LLM-шлюз сайдкара недоступен", exc_info=True)
        return None

    try:
        content = str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError):
        logger.warning("LLM-шлюз сайдкара: неожиданная форма ответа")
        return None

    usage = data.get("usage")
    if not isinstance(usage, dict):
        # Ответ без usage — не повод молчать: значит вызов не будет затарифицирован.
        logger.warning("LLM-шлюз сайдкара не вернул usage — вызов останется не списанным")
        usage = {}
    return content, usage
