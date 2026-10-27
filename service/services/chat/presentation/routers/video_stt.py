"""Private, grant-authenticated STT. No user/public transcription endpoint."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import (
    get_billing_service,
    get_job_service,
    get_optional_redis_client,
)
from service.services.chat.application.video_stt.execution import (
    MAX_AUDIO_BYTES,
    MAX_DURATION_SEC,
    VideoSttExecutor,
    VideoSttFailure,
)
from service.services.chat.application.video_stt.grants import authorize_video_stt
from service.services.chat.application.video_stt.stream import source_transcription_stream
from service.services.chat.application.workspace_collaboration import CollaborationError
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    WhisperLocalTranscriber,
)

router = APIRouter(prefix="/internal/video-stt", include_in_schema=False)


class VideoSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


@router.post("/from-video")
async def transcribe_source(request: Request, payload: VideoSourceRequest):
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
    redis = get_optional_redis_client(request)

    async def authorize():
        return await authorize_video_stt(
            redis,
            get_job_service(request).repository,
            token=token,
            duration_limit_sec=MAX_DURATION_SEC,
        )

    try:
        job = await authorize()
        return source_transcription_stream(
            job,
            redis=redis,
            billing=get_billing_service(request),
            url=payload.url,
            authorize=authorize,
        )
    except (VideoSttFailure, CollaborationError):
        raise HTTPException(status_code=403, detail={"code": "forbidden"}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "unavailable"}) from None


@router.post("/transcribe")
async def transcribe_video(request: Request, duration_limit_sec: float):
    # Grant/job/control checks precede reading audio or reserving any money.
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    redis = get_optional_redis_client(request)
    try:
        job = await authorize_video_stt(
            redis,
            get_job_service(request).repository,
            token=token,
            duration_limit_sec=duration_limit_sec,
        )
        if not 0 < duration_limit_sec <= MAX_DURATION_SEC:
            raise VideoSttFailure("invalid")
        audio = bytearray()
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(audio) + len(chunk) > MAX_AUDIO_BYTES:
                    raise VideoSttFailure("too_large")
                audio.extend(chunk)
        whisper = WhisperLocalTranscriber()
        executor = VideoSttExecutor(redis, get_billing_service(request), whisper)
        return await executor.execute(job, bytes(audio))
    except (VideoSttFailure, CollaborationError) as exc:
        code = exc.code if isinstance(exc, VideoSttFailure) else "forbidden"
        status = {
            "forbidden": 403,
            "invalid": 422,
            "too_large": 413,
            "insufficient_credits": 402,
            "busy": 409,
            "interrupted": 409,
            "intent_conflict": 409,
        }.get(code, 503)
        raise HTTPException(status_code=status, detail={"code": code}) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "unavailable"}) from None
