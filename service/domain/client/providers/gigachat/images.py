"""Run-private native image uploads bound to the admitted GigaChat client.

Only bounded inline raster input is accepted. No remote URL fetching, persistent
provider-file IDs, or generic user storage is introduced here. Official contract:
https://developers.sber.ru/docs/ru/gigachat/guides/working-with-files
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from service.domain.client.protocol import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderProtocolError,
    classify_provider_failure,
)
from service.domain.client.providers.image_transport_privacy import private_image_transport

logger = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 15_000_000
MAX_REQUEST_BYTES = 80_000_000
MAX_IMAGES = 10
_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/bmp": "BMP", "image/tiff": "TIFF"}


def _invalid(code: ProviderFailureCode = ProviderFailureCode.PAYLOAD) -> ProviderProtocolError:
    return ProviderProtocolError(ProviderFailure(code=code, retryable=False, provider="gigachat"))


def _image(value: Any) -> tuple[bytes, str]:
    if not isinstance(value, dict) or not isinstance(value.get("url"), str):
        raise _invalid()
    url = value["url"]
    prefix, separator, encoded = url.partition(",")
    mime = prefix.removeprefix("data:").removesuffix(";base64")
    if (
        not separator
        or prefix != f"data:{mime};base64"
        or mime not in _FORMATS
        or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4
    ):
        raise _invalid()
    try:
        payload = base64.b64decode(encoded, validate=True)
        if not payload or len(payload) > MAX_IMAGE_BYTES:
            raise _invalid()
        with private_image_transport(), Image.open(BytesIO(payload)) as image:
            if (
                image.format != _FORMATS[mime]
                or image.width < 1
                or image.height < 1
                or image.width > 20_000
                or image.height > 20_000
                or image.width * image.height > 40_000_000
            ):
                raise _invalid()
            image.verify()
    except (
        binascii.Error,
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ):
        raise _invalid() from None
    return payload, mime


def _plan(messages: list[dict]) -> list[tuple[dict, tuple[bytes, str] | None]]:
    planned: list[tuple[dict, tuple[bytes, str] | None]] = []
    count = size = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            planned.append((dict(message), None))
            continue
        if message.get("attachments"):
            raise _invalid()
        text: list[str] = []
        emitted = False
        for block in content:
            if not isinstance(block, dict):
                raise _invalid()
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text.append(block["text"])
                size += len(block["text"].encode("utf-8"))
            elif block.get("type") == "image_url" and message.get("role") == "user":
                image = _image(block.get("image_url"))
                count += 1
                size += len(image[0])
                if count > MAX_IMAGES or size > MAX_REQUEST_BYTES:
                    raise _invalid()
                planned.append(({**message, "content": "\n".join(text)}, image))
                text = []
                emitted = True
            else:
                raise _invalid()
        if text or not emitted:
            planned.append(({**message, "content": "\n".join(text)}, None))
    if size > MAX_REQUEST_BYTES:
        raise _invalid()
    return planned


async def _upload(client: Any, image: tuple[bytes, str]) -> str:
    payload, mime = image
    # Never retry uploads with an unknown acknowledgement. The generation-bound
    # client's existing TLS/auth/proxy transport is reused without rebuilding it.
    try:
        with private_image_transport():
            response = await client.post(
                "/files",
                cast_to=object,
                body={"purpose": "general"},
                files={"file": (f"gpthub-{uuid4()}.{_FORMATS[mime].lower()}", payload, mime)},
                options={
                    "headers": {"Content-Type": "multipart/form-data"},
                    "max_retries": 0,
                    "timeout": 10,
                },
            )
        value = response.get("id") if isinstance(response, dict) else None
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise _invalid(ProviderFailureCode.PROTOCOL)
        return value
    except ProviderProtocolError:
        raise
    except Exception as exc:
        raise ProviderProtocolError(classify_provider_failure(exc, provider="gigachat")) from None


async def _cleanup(client: Any, identities: list[str]) -> None:
    async def remove(identity: str) -> bool:
        try:
            with private_image_transport():
                await client.post(
                    f"/files/{identity}/delete",
                    cast_to=object,
                    options={"max_retries": 0, "timeout": 2},
                )
            return True
        except Exception:
            return False

    if not identities:
        return
    try:
        async with asyncio.timeout(3):
            outcomes = await asyncio.gather(*(remove(identity) for identity in identities))
        if not all(outcomes):
            logger.warning("provider_image_cleanup provider=gigachat status=failed")
    except TimeoutError:
        logger.warning("provider_image_cleanup provider=gigachat status=timeout")


@asynccontextmanager
async def native_image_messages(
    client: Any, provider: str, messages: list[dict], *, preserve_completed: bool = False
):
    if provider != "gigachat":
        yield messages
        return
    planned = _plan(messages)
    if not any(image is not None for _message, image in planned):
        yield [message for message, _image_value in planned]
        return
    async with _uploaded_messages(client, planned, preserve_completed=preserve_completed) as native:
        yield native


@asynccontextmanager
async def _uploaded_messages(client: Any, planned: list, *, preserve_completed: bool):
    """Keep uploaded IDs private and alive exactly through the provider round."""
    identities: list[str] = []
    converted: list[dict] = []
    completed = False
    try:
        for message, image in planned:
            if image is not None:
                upload = asyncio.create_task(_upload(client, image))
                try:
                    identity = await asyncio.shield(upload)
                except asyncio.CancelledError:
                    # Preserve a just-completed upload ID for cleanup, but do not
                    # wait indefinitely or invent an ID after an unknown ACK.
                    try:
                        identities.append(await asyncio.wait_for(upload, 2))
                    except (Exception, asyncio.CancelledError):
                        logger.warning("provider_image_upload provider=gigachat status=uncertain")
                    raise
                identities.append(identity)
                message = {**message, "attachments": [identity]}
            converted.append(message)
        yield converted
        completed = True
    finally:
        cleanup = asyncio.create_task(_cleanup(client, identities))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup)
            # An already received non-stream result must reach ledger accounting
            # even if cancellation arrives during best-effort file deletion.
            if not (completed and preserve_completed):
                raise
