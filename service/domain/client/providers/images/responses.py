"""Только встроенные изображения; внешние URL результата не скачиваются."""

from types import SimpleNamespace
from typing import Any


def value(item: Any, key: str, default: Any = None) -> Any:
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def image_base64(response: Any) -> str:
    data = value(response, "data") or []
    if data:
        encoded = value(data[0], "b64_json")
        return encoded.strip() if isinstance(encoded, str) else ""
    choices = value(response, "choices") or []
    if not choices:
        return ""
    message = value(choices[0], "message")
    images = value(message, "images") or []
    if not images and callable(dump := getattr(message, "model_dump", None)):
        images = value(dump(), "images") or []
    if not images:
        return ""
    first = images[0]
    image_url = value(first, "image_url", first if isinstance(first, str) else None)
    url = value(image_url, "url") if not isinstance(image_url, str) else image_url
    if not isinstance(url, str) or not url.startswith("data:image/") or ";base64," not in url:
        return ""
    return url.split(";base64,", 1)[1].strip()


def dedicated_response(response: Any) -> SimpleNamespace:
    """Привести фактические токены Image API к общей форме, не оценивая их по цене."""
    usage = value(response, "usage")
    prompt = value(usage, "prompt_tokens", value(usage, "input_tokens", 0))
    completion = value(usage, "completion_tokens", value(usage, "output_tokens", 0))
    return SimpleNamespace(
        data=value(response, "data") or [],
        choices=[],
        usage=SimpleNamespace(prompt_tokens=prompt or 0, completion_tokens=completion or 0),
    )
