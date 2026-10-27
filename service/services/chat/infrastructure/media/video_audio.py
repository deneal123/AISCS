"""Authenticated bounded stream from video; never follow a response redirect."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass, field

import httpx

from service.services.chat.application.video_stt.execution import VideoSttFailure

MAX_AUDIO_BYTES = 25 * 1024 * 1024
SAFE_SOURCE_FAILURES = frozenset(
    {
        "source_rate_limited",
        "source_access_challenge",
        "source_access_denied",
        "watch_timeout",
        "too_long",
        "too_large",
        "unsupported_source",
        "toolchain_failed",
        "unsafe_url",
    }
)


@dataclass(frozen=True, slots=True)
class VideoAudio:
    content: bytes = field(repr=False)
    duration_sec: float
    sha256: str


async def fetch_video_audio(
    base_url: str,
    key: str,
    url: str,
    *,
    timeout_sec: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> VideoAudio:
    if not base_url or not key or not math.isfinite(timeout_sec) or timeout_sec <= 0:
        raise VideoSttFailure("unavailable")
    try:
        async with (
            asyncio.timeout(timeout_sec),
            httpx.AsyncClient(
                timeout=timeout_sec, transport=transport, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(
                "POST",
                base_url.rstrip("/") + "/audio",
                json={"url": url},
                headers={"Authorization": f"Bearer {key}"},
            ) as response,
        ):
            if response.status_code != 200:
                # Error bodies can contain source URL/credentials. Never consume them.
                code = response.headers.get("x-video-failure", "")
                if response.status_code not in {400, 413, 502} or code not in SAFE_SOURCE_FAILURES:
                    code = "unavailable"
                raise VideoSttFailure("timeout" if code == "watch_timeout" else code)
            if response.headers.get("content-type", "").split(";", 1)[0] != "audio/mpeg":
                raise VideoSttFailure("protocol")
            expected_size = int(response.headers.get("content-length", "0"))
            duration = float(response.headers.get("x-audio-duration", "0"))
            expected_hash = response.headers.get("x-audio-sha256", "")
            if (
                not 0 < expected_size <= MAX_AUDIO_BYTES
                or not math.isfinite(duration)
                or not 0 < duration <= 7200
                or re.fullmatch(r"[a-f0-9]{64}", expected_hash) is None
            ):
                raise VideoSttFailure("protocol")
            content = bytearray()
            digest = hashlib.sha256()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > min(MAX_AUDIO_BYTES, expected_size):
                    raise VideoSttFailure("too_large")
                content.extend(chunk)
                digest.update(chunk)
            if len(content) != expected_size or digest.hexdigest() != expected_hash:
                raise VideoSttFailure("protocol")
            return VideoAudio(bytes(content), duration, digest.hexdigest())
    except VideoSttFailure:
        raise
    except (httpx.HTTPError, TimeoutError):
        raise VideoSttFailure("unavailable") from None
    except (ValueError, TypeError):
        raise VideoSttFailure("protocol") from None
