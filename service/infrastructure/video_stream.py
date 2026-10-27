"""Private video acquisition stream; only bounded progress is projected to events."""

from __future__ import annotations

import asyncio
import json

import httpx

from service.domain.runners.tool_runtime.progress import report_video_progress
from service.infrastructure.sidecar import SidecarClient, SidecarUnavailable

_MAX_FRAME_BYTES = 64 * 1024 * 1024


async def _read_legacy_json(response: httpx.Response) -> dict:
    body = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=min(65_536, _MAX_FRAME_BYTES + 1)):
        if len(body) + len(chunk) > _MAX_FRAME_BYTES:
            raise SidecarUnavailable("video", "protocol")
        body.extend(chunk)
    result = json.loads(body)
    if not isinstance(result, dict):
        raise SidecarUnavailable("video", "protocol")
    return result


async def acquire_video(client: SidecarClient, payload: dict, key: str) -> dict:
    # Test/dev clients predating the stream contract retain the same single-call seam.
    if not isinstance(client, SidecarClient):
        return await client.request_json(
            "POST",
            "/watch",
            json_body=payload,
            headers={"Authorization": f"Bearer {key}"} if key else None,
        )
    headers = client._headers({"Accept": "application/x-ndjson", "Authorization": f"Bearer {key}"})
    try:
        async with (
            asyncio.timeout(client._timeout),
            httpx.AsyncClient(
                timeout=client._timeout,
                transport=client._transport,
                trust_env=False,
                follow_redirects=False,
            ) as transport,
            transport.stream(
                "POST", client._base + "/watch", json=payload, headers=headers
            ) as response,
        ):
            if response.status_code >= 400:
                # Do not retain error bodies or use provider text in diagnostics.
                raise client._classify(response.status_code, "unavailable", "")
            if "application/x-ndjson" not in response.headers.get("content-type", ""):
                # Rolling deployments accept the previous successful JSON response.
                return await _read_legacy_json(response)
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                if len(buffer) > _MAX_FRAME_BYTES:
                    raise SidecarUnavailable("video", "protocol")
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    frame = json.loads(line)
                    if not isinstance(frame, dict):
                        raise SidecarUnavailable("video", "protocol")
                    kind = frame.get("type")
                    if kind == "progress":
                        report_video_progress(frame)
                    elif kind == "result" and isinstance(frame.get("result"), dict):
                        return frame["result"]
                    elif kind == "error":
                        status = frame.get("status")
                        code = frame.get("code")
                        safe = (
                            code
                            if code
                            in {
                                "watch_timeout",
                                "too_long",
                                "too_large",
                                "unsupported_source",
                                "toolchain_failed",
                                "source_rate_limited",
                                "source_access_challenge",
                                "source_access_denied",
                            }
                            else "unavailable"
                        )
                        raise client._classify(
                            status if status in {400, 413, 500, 502, 504} else 502, safe, ""
                        )
                    else:
                        raise SidecarUnavailable("video", "protocol")
            raise SidecarUnavailable("video", "protocol")
    except (TimeoutError, httpx.TimeoutException):
        raise client._classify(504, "timeout", "") from None
    except httpx.HTTPError:
        raise SidecarUnavailable("video", "transport_error") from None
    except (ValueError, TypeError, RecursionError):
        raise SidecarUnavailable("video", "protocol") from None
