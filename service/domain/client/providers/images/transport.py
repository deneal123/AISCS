"""Протокол выбирается до платного запроса, без пробного вызова другого endpoint."""

import asyncio
from typing import Any

from openai.types import ImagesResponse

from service.domain.client.calls.harness_transport import require_explicit_transport_allowed
from service.domain.client.providers.image_transport_privacy import private_image_transport
from service.domain.execution.context import RunExecutionContext
from service.shared import deadline

from .responses import dedicated_response


class ImageBillingUnavailable(RuntimeError):
    """Запрос запрещён до подтверждения отдельной тарификации изображений."""


def uses_dedicated_api(execution: RunExecutionContext, provider: str | None, model: str) -> bool:
    if provider not in {"routerai", "openrouter"} or execution.provider_snapshot is None:
        return False
    record = next(
        (
            item
            for item in execution.provider_snapshot.records.get(provider, ())
            if item.model_id == model
        ),
        None,
    )
    return record is not None and record.supports("image_output") and not record.supports("chat")


async def create_image(
    client: Any,
    *,
    dedicated: bool,
    model: str,
    messages: list[dict[str, Any]],
    extra_body: dict[str, Any],
) -> Any:
    # Пока durable harness не поддерживает receipts изображений, запрещаем
    # обход серверного grant через прямой SDK-вызов. Обычный Chat не ограничивается.
    require_explicit_transport_allowed()
    if dedicated:
        from service.settings import config

        if not config.agents.image_only_api_enabled:
            raise ImageBillingUnavailable("image_billing_unavailable")
    with private_image_transport():
        async with asyncio.timeout(deadline.clamp(180)):
            if not dedicated:
                return await client.chat.completions.create(
                    model=model, messages=messages, extra_body=extra_body
                )
            content = messages[0]["content"]
            body = {"model": model, "n": 1}
            if isinstance(content, str):
                body["prompt"] = content
            else:
                body["prompt"] = content[0]["text"]
                body["input_references"] = [content[1]]
            response = await client.with_options(timeout=deadline.clamp(180), max_retries=0).post(
                "/images", cast_to=ImagesResponse, body=body
            )
            return dedicated_response(response)
