"""Private, confirmed-job local STT bridge. No provider fallback or tool retry."""

from __future__ import annotations

import asyncio
import json
import math

import httpx

from service.domain.execution.context import current_execution
from service.domain.runners.tool_runtime.progress import report_video_progress
from service.infrastructure.sidecar import SidecarUnavailable

MAX_FRAME_BYTES = 4 * 1024 * 1024
SAFE_STT_FAILURES = frozenset(
    {
        "timeout",
        "source_rate_limited",
        "source_access_challenge",
        "source_access_denied",
        "too_long",
        "too_large",
        "unsupported_source",
        "toolchain_failed",
        "protocol",
    }
)


async def acquire_local_transcript(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> dict | None:
    execution = current_execution()
    if execution is None or not execution.policy.flag("video_summary_active"):
        return None
    ref = execution.resources.workspace_ref or {}
    binding = ref.get("video_stt")
    if not isinstance(binding, dict) or not binding.get("grant") or not binding.get("endpoint"):
        return None
    budget = execution.run_deadline
    if execution.cancelled or (budget is not None and budget.must_finalize()):
        raise SidecarUnavailable("video", "timeout")
    timeout = budget.clamp(480) if budget is not None else 480
    try:
        async with (
            asyncio.timeout(timeout),
            httpx.AsyncClient(
                timeout=timeout, transport=transport, follow_redirects=False, trust_env=False
            ) as client,
            client.stream(
                "POST",
                binding["endpoint"],
                json={"url": url},
                headers={"Authorization": "Bearer " + binding["grant"]},
            ) as response,
        ):
            if response.status_code != 200:
                raise SidecarUnavailable("video", "unavailable")
            if response.headers.get("content-type", "").split(";", 1)[0] != "application/x-ndjson":
                raise SidecarUnavailable("video", "protocol")
            buffer = bytearray()
            async for chunk in response.aiter_bytes():
                buffer.extend(chunk)
                if len(buffer) > MAX_FRAME_BYTES:
                    raise SidecarUnavailable("video", "protocol")
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    frame = json.loads(line)
                    if not isinstance(frame, dict):
                        raise SidecarUnavailable("video", "protocol")
                    if frame.get("type") == "progress":
                        _progress(frame)
                    elif frame.get("type") == "result":
                        return _source(frame.get("result"))
                    elif frame.get("type") == "error":
                        code = frame.get("code")
                        code = (
                            code
                            if isinstance(code, str) and code in SAFE_STT_FAILURES
                            else "unavailable"
                        )
                        raise SidecarUnavailable("video", code)
                    else:
                        raise SidecarUnavailable("video", "protocol")
            raise SidecarUnavailable("video", "protocol")
    except (TimeoutError, httpx.TimeoutException):
        raise SidecarUnavailable("video", "timeout") from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise SidecarUnavailable("video", "protocol") from None


def _progress(frame: dict) -> None:
    if frame.get("stage") not in {"download", "transcript"}:
        raise SidecarUnavailable("video", "protocol")
    elapsed = frame.get("elapsed_sec", 0)
    if type(elapsed) is not int or not 0 <= elapsed <= 7200:
        raise SidecarUnavailable("video", "protocol")
    report_video_progress(
        {
            "stage": frame["stage"],
            "heartbeat": frame.get("heartbeat") is True,
            "elapsed_sec": elapsed,
        }
    )


def _source(result) -> dict:
    if not isinstance(result, dict):
        raise SidecarUnavailable("video", "protocol")
    duration = result.get("duration_sec")
    cues = result.get("segments")
    if (
        type(duration) not in {int, float}
        or not 0 < duration <= 7200
        or not math.isfinite(duration)
        or not isinstance(cues, list)
        or not 0 < len(cues) <= 20_000
    ):
        raise SidecarUnavailable("video", "protocol")
    previous = -1.0
    validated = []
    for cue in cues:
        if not isinstance(cue, dict):
            raise SidecarUnavailable("video", "protocol")
        start, end, text = cue.get("t_sec"), cue.get("end_sec"), cue.get("text")
        if (
            type(start) not in {int, float}
            or type(end) not in {int, float}
            or not 0 <= start <= end <= duration + 1
            or start < previous
            or not math.isfinite(start)
            or not math.isfinite(end)
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise SidecarUnavailable("video", "protocol")
        previous = start
        validated.append({"t_sec": start, "end_sec": end, "text": text})
    transcript_text = result.get("text")
    if not isinstance(transcript_text, str) or " ".join(
        " ".join(c["text"] for c in validated).split()
    ) != " ".join(transcript_text.split()):
        raise SidecarUnavailable("video", "protocol")
    return {"duration_sec": duration, "transcript": validated, "frames": [], "warnings": []}
