"""One private source/STT operation with bounded progress and disconnect cleanup."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from typing import Any

from fastapi.responses import StreamingResponse

from service.services.chat.application.video_stt.execution import (
    MAX_DURATION_SEC,
    AuthorizedVideoSttJob,
    VideoSttExecutor,
    VideoSttFailure,
)
from service.services.chat.infrastructure.media.video_audio import fetch_video_audio
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    WhisperLocalTranscriber,
)
from service.settings import config


def source_transcription_stream(
    job: AuthorizedVideoSttJob,
    *,
    redis: Any,
    billing: Any,
    url: str,
    authorize: Callable[[], Awaitable[AuthorizedVideoSttJob]],
) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        stages: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
        stages.put_nowait("download")

        async def operation() -> dict[str, Any]:
            audio = await fetch_video_audio(
                config.agents.video_url,
                config.agents.video_api_key,
                url,
                timeout_sec=min(420, float(config.agents.video_timeout_sec)),
            )
            # A cancelled/paused/terminal job cannot start STT after media retrieval.
            await authorize()
            stages.put_nowait("transcript")
            scoped = replace(
                job, duration_limit_sec=min(MAX_DURATION_SEC, math.ceil(audio.duration_sec) + 1)
            )
            return await VideoSttExecutor(redis, billing, WhisperLocalTranscriber()).execute(
                scoped, audio.content
            )

        task = asyncio.create_task(operation())
        reader: asyncio.Task[str] | None = None
        stage = "download"
        try:
            while not task.done() or not stages.empty():
                reader = asyncio.create_task(stages.get())
                done, _ = await asyncio.wait(
                    {reader, task}, timeout=10, return_when=asyncio.FIRST_COMPLETED
                )
                if reader in done:
                    stage = reader.result()
                    heartbeat = False
                else:
                    reader.cancel()
                    await asyncio.gather(reader, return_exceptions=True)
                    if task.done():
                        break
                    heartbeat = True
                reader = None
                yield (
                    json.dumps(
                        {
                            "type": "progress",
                            "stage": stage,
                            "heartbeat": heartbeat,
                            "elapsed_sec": int(loop.time() - started),
                        }
                    )
                    + "\n"
                )
            result = task.result()
            yield json.dumps({"type": "result", "result": result}, ensure_ascii=False) + "\n"
        except VideoSttFailure as exc:
            yield json.dumps({"type": "error", "code": exc.code}) + "\n"
        except Exception:
            yield json.dumps({"type": "error", "code": "unavailable"}) + "\n"
        finally:
            for pending in (reader, task):
                if pending is not None and not pending.done():
                    pending.cancel()
            await asyncio.gather(
                *(pending for pending in (reader, task) if pending is not None),
                return_exceptions=True,
            )

    return StreamingResponse(body(), media_type="application/x-ndjson")
