"""Генерация изображения — общий инструмент для всех, кому нужна картинка.

⚠️ ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ. Логика жила приватным методом `ImageGenerationAgent`, то есть
была доступна ровно одному агенту. Генератору презентаций картинки нужны не меньше, а
дотянуться до чужого приватного метода он мог бы только импортом агента — а это тянет за
собой весь его пайплайн (гардрейлы, раскрытие follow-up, события).

Здесь — только «дай картинку по описанию». Кто и зачем её просит, модуль не знает.
"""

from __future__ import annotations

import logging

from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.usage_ledger import UsageKind, receipt_from_usage

logger = logging.getLogger(__name__)

# Фикс-эквивалент за изображение, когда провайдер не вернул usage.
#
# ⚠️ БЕЗ НЕГО КАРТИНКИ БЕСПЛАТНЫ. Провайдеры image-модальности обычно не отдают `usage`,
# и `build_token_usage_meta` на пустом накопителе вернул бы None — вызов состоялся,
# платформа заплатила, счёт нулевой. Значение и форма те же, что у агента-генератора:
# расхождение между ними означало бы, что одна и та же работа стоит по-разному в
# зависимости от того, кто её попросил.
IMAGE_FIXED_EQUIVALENT_TOKENS = 1024


async def generate_image_b64(
    image_model: str,
    prompt: str,
    execution: RunExecutionContext | None = None,
    reference_image_url: str | None = None,
    reason_out: dict | None = None,
    usage_kind: str | UsageKind | None = None,
) -> str:
    """Сгенерировать изображение и вернуть base64 PNG (без префикса ``data:``).

    ``reference_image_url`` — картинка-РЕФЕРЕНС для image-to-image («перегенерируй с
    другим цветом волос», «сделай фон темнее»). Подаётся тем же сообщением рядом с
    текстом (multimodal content); модель редактирует её, а не рисует с нуля. Может быть
    ``data:``-URL или http(s). None — обычная генерация из текста.

    ⚠️ Агрегаторы (OpenRouter/RouterAI) НЕ поддерживают OpenAI ``/images/generations`` —
    там 404. Картинки у них генерируются через chat/completions с image-модальностью:
    ответ приходит в ``message.images[].image_url.url`` как ``data:image/...;base64,...``.
    Клиент адресуем напрямую: фасадный `create_chat_completion` не пробрасывает
    `extra_body` с `modalities`.

    ⚠️ Модель адресуем ВЛАДЕЛЬЦУ из индекса каталога: активный провайдер может её не
    знать и вернуть 404.
    """
    execution = require_execution(execution)

    from service.domain.client.provider_operations import ProviderOperation

    client = None
    provider_name: str | None = None
    try:
        admission = execution.provider_admission
        if admission is not None:
            decision = admission.admit_first(
                operation=ProviderOperation.IMAGE_OUTPUT,
                prefer=image_model,
                pick_model=lambda models, prefer: (
                    prefer if prefer in models else models[0] if models else None
                ),
            )
            if decision is not None:
                provider_name = decision.provider
                image_model = decision.model or image_model
                client = decision.client
        else:
            from service.domain.client.provider_compat import resolve_model_client

            provider_name, client = await resolve_model_client(image_model)
    except Exception:  # noqa: BLE001 — каталог недоступен: пробуем активного
        client = None
    if client is None:
        return ""
    if reference_image_url:
        # image-to-image: текст + картинка в одном user-сообщении. Порядок «текст, потом
        # картинка» — как в живой проверке провайдера; менять без причины не стоит.
        content: list[dict] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": reference_image_url}},
        ]
        messages: list[dict] = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    # 🔴 ОДИН ПОВТОР. Пустой ответ image-модальности — задокументированный ЧАСТЫЙ случай
    # (перегрузка, отказ модерации, «извинение» текстом), и он не отличим от отказа
    # навсегда. Живой инцидент: пользователь получил «не удалось» и стену промпта, а обе
    # проверки тем же запросом сразу после прошли — сбой был разовым. Повтор дешевле, чем
    # ответ без картинки: мы и так платим провайдеру за пустую попытку, а пользователь
    # платит за неё НОЛЬ (см. гейт usage ниже).
    resp = None
    model_result = None
    b64 = ""
    for attempt in (1, 2):
        model_result = await invoke_model_call(
            client.chat.completions.create,
            model=image_model,
            kind=usage_kind,
            provider_name=provider_name,
            chargeable=False,
            estimate_missing_usage=False,
            execution=execution,
            messages=messages,
            extra_body={"modalities": ["image", "text"]},
        )
        resp = model_result.response
        b64 = _extract_b64(resp)
        if b64:
            break
        logger.warning(
            "image generation returned no artifact attempt=%d/2 finish=%s",
            attempt,
            _bounded_finish_reason(resp),
        )
    if not b64 and reason_out is not None:
        reason_out["failure_code"] = "empty_image"
        reason_out["finish_reason"] = _bounded_finish_reason(resp)
    # ⚠️ USAGE ТОЛЬКО ЗА РЕАЛЬНО ПОЛУЧЕННУЮ КАРТИНКУ. Провайдер image-модальности иногда
    # отвечает БЕЗ изображения (перегрузка, отказ модерации, «извинение» текстом), но с
    # непустым usage — и списывает с нас. Раньше `accumulate_usage` стоял здесь
    # безусловно: image-токены попадали в usage вызывающего, а тот, увидев пустой b64,
    # уходил в текстовый промпт-фолбэк. Пользователь платил по ДОРОГОМУ image-тарифу за
    # изображение, которого не получил, плюс за фолбэк-промпт. Тот же принцип, что в
    # web_search и на таймауте синтеза: берём с пользователя только за то, что он
    # получил. Неуспешный вызов к провайдеру — наш убыток на ретрае, не счёт клиенту.
    if b64 and model_result is not None:
        receipt = model_result.usage
        if receipt.total <= 0:
            receipt = receipt_from_usage(
                fixed_equivalent_usage(image_model),
                provider=provider_name,
                model=image_model,
                kind=usage_kind,
                receipt_id=receipt.receipt_id,
                estimated=True,
                chargeable=True,
            )
            execution.usage.record(receipt)
        else:
            receipt = execution.usage.set_chargeable(receipt.receipt_id) or receipt
    return b64


def _bounded_finish_reason(resp) -> str:
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return "unknown"
    value = str(getattr(choices[0], "finish_reason", "") or "").strip().lower()
    return value if value in {"stop", "length", "content_filter", "safety"} else "unknown"


def _extract_b64(resp) -> str:
    """Достать base64 из ответа image-модальности. Пусто, если картинки нет."""
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return ""
    msg = choices[0].message
    images = getattr(msg, "images", None)
    if not images and hasattr(msg, "model_dump"):
        images = (msg.model_dump() or {}).get("images")
    if not images:
        return ""
    first = images[0]
    url = ""
    if isinstance(first, dict):
        image_url = first.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else (image_url or "")
    elif isinstance(first, str):
        url = first
    if not url or "," not in url:
        return ""
    return url.split(",", 1)[1].strip()


def fixed_equivalent_usage(model: str | None, count: int = 1) -> dict:
    """Фикс-эквивалент за ``count`` изображений, когда провайдер не отдал usage.

    ``model`` ОБЯЗАТЕЛЕН по смыслу: без него `resolve_model_price(None)` уходит в
    ДЕФОЛТ-цену вместо цены image-модели, и картинка тарифится по чужому тарифу.
    """
    return {
        "prompt": 0,
        "completion": IMAGE_FIXED_EQUIVALENT_TOKENS * max(0, int(count)),
        "total": IMAGE_FIXED_EQUIVALENT_TOKENS * max(0, int(count)),
        "model": model,
        "estimated": True,
    }
