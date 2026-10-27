"""Metered local STT execution; transport must first authenticate the owned job.

The private journal is not an event, assistant metadata or an LLM usage receipt.
A settlement retry never reruns Whisper. An interrupted running attempt is not
automatically retried: its execution outcome is unknown.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any
from uuid import uuid4

from service.infrastructure.cache.manager import call_redis
from service.services.chat.application.video_stt.settlement import (
    commit_charge,
    journal_key,
    save_pending,
)
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    TranscriptionTooExpensive,
    whisper_transcription_credits,
)
from service.settings import config

MAX_AUDIO_BYTES = 64 * 1024 * 1024
MAX_TRANSCRIPT_CHARS = 2_000_000
MAX_DURATION_SEC = 7200.0
JOURNAL_TTL_SEC = 7200
LOCK_TTL_SEC = 900
TRANSCRIBE_TIMEOUT_SEC = 600
_RELEASE_LOCK = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class VideoSttFailure(Exception):
    """Closed codes only; never retain a transport/provider exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AuthorizedVideoSttJob:
    """Backend-created binding, not populated from arbitrary request fields."""

    owner_id: str
    job_id: str
    model: str
    language: str
    duration_limit_sec: float


class VideoSttExecutor:
    def __init__(self, redis: Any, billing: Any, whisper: Any) -> None:
        self.redis = redis
        self.billing = billing
        self.whisper = whisper

    async def execute(self, job: AuthorizedVideoSttJob, audio: bytes) -> dict[str, Any]:
        if (
            not job.owner_id
            or not job.job_id
            or not job.model
            or not math.isfinite(job.duration_limit_sec)
            or not 0 < job.duration_limit_sec <= MAX_DURATION_SEC
            or not 0 < len(audio) <= MAX_AUDIO_BYTES
        ):
            raise VideoSttFailure("invalid")
        key = journal_key(job.owner_id, job.job_id)
        # No expiring-lock retry can steal execution: the running journal remains
        # a tombstone even if the worker dies or the lock expires.
        lock_token = uuid4().hex
        acquired = await call_redis(
            self.redis, "set", key + ":lock", lock_token, nx=True, ex=LOCK_TTL_SEC
        )
        if not acquired:
            raise VideoSttFailure("busy")
        try:
            return await self._locked(key, job, audio)
        except VideoSttFailure:
            raise
        except Exception:
            raise VideoSttFailure("unavailable") from None
        finally:
            try:
                await call_redis(self.redis, "eval", _RELEASE_LOCK, 1, key + ":lock", lock_token)
            except Exception:
                raise VideoSttFailure("unavailable") from None

    async def _save(self, key: str, value: dict[str, Any]) -> None:
        if value["status"] == "pending_charge":
            await save_pending(self.redis, key, value, JOURNAL_TTL_SEC)
        else:
            await call_redis(
                self.redis, "set", key, json.dumps(value, separators=(",", ":")), ex=JOURNAL_TTL_SEC
            )

    async def _locked(self, key: str, job: AuthorizedVideoSttJob, audio: bytes) -> dict[str, Any]:
        digest = hashlib.sha256(audio).hexdigest()
        raw = await call_redis(self.redis, "get", key)
        state = json.loads(raw) if raw else None
        if state is not None:
            if (
                state.get("audio_digest") != digest
                or state.get("owner_id") != job.owner_id
                or state.get("job_id") != job.job_id
                or state.get("model") != job.model
                or state.get("language") != job.language
                # Redis cjson settlement rounds floating-point numbers. Accept
                # serialization noise only, not a changed prepaid duration.
                or not _same_duration(state.get("duration_limit_sec"), job.duration_limit_sec)
            ):
                raise VideoSttFailure("intent_conflict")
            if state.get("status") in {"pending_charge", "completed"}:
                return await self._settle(key, job, state)
            raise VideoSttFailure("interrupted")
        if not self.whisper.enabled:
            raise VideoSttFailure("unavailable")
        credits, maximum_rub = whisper_transcription_credits(job.duration_limit_sec, job.model)
        unit = Decimal(str(config.billing.credit_unit_rub or 0.003))
        if (
            not math.isfinite(maximum_rub)
            or maximum_rub < 0
            or credits < 0
            or not unit.is_finite()
            or unit <= 0
        ):
            raise VideoSttFailure("unavailable")
        reservation = await self.billing.reserve(
            job.owner_id, credits=credits, ttl_seconds=LOCK_TTL_SEC
        )
        if not reservation:
            raise VideoSttFailure("insufficient_credits")
        state = {
            "status": "running",
            "audio_digest": digest,
            "reservation_id": reservation,
            "model": job.model,
            "language": job.language,
            "duration_limit_sec": job.duration_limit_sec,
            "owner_id": job.owner_id,
            "job_id": job.job_id,
        }
        try:
            await self._save(key, state)
            async with asyncio.timeout(TRANSCRIBE_TIMEOUT_SEC):
                result = await self.whisper.transcribe(
                    audio,
                    model=job.model,
                    language=job.language,
                    max_duration_sec=job.duration_limit_sec,
                    include_segments=True,
                )
            text = result.get("text")
            duration = result.get("duration_sec")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > MAX_TRANSCRIPT_CHARS
                or isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or not 0 < duration <= job.duration_limit_sec
                or result.get("model") != job.model
            ):
                raise VideoSttFailure("protocol")
            segments = _validated_segments(result.get("segments"), text, duration)
            # Freeze the price accepted at reservation, not a future hot-setting.
            rub = (
                Decimal(str(maximum_rub))
                * Decimal(str(duration))
                / Decimal(str(job.duration_limit_sec))
            )
            state.update(
                status="pending_charge",
                text=text,
                duration_sec=duration,
                segments=segments,
                credits=int((rub / unit).to_integral_value(rounding=ROUND_CEILING)),
                raw_cost_rub=float(rub),
            )
            await self._save(key, state)
        except (Exception, asyncio.CancelledError) as exc:
            # Once a transcript is durable, leave its reservation for settlement.
            # Never refund usage merely because the response consumer disconnected.
            if state["status"] != "pending_charge":
                await self.billing.release_reservation(reservation, user_id=job.owner_id)
            if isinstance(exc, asyncio.CancelledError):
                raise
            code = (
                "insufficient_credits"
                if isinstance(exc, TranscriptionTooExpensive)
                else "unavailable"
            )
            if isinstance(exc, VideoSttFailure):
                code = exc.code
            raise VideoSttFailure(code) from None
        return await self._settle(key, job, state)

    async def _settle(
        self, key: str, job: AuthorizedVideoSttJob, state: dict[str, Any]
    ) -> dict[str, Any]:
        if state["status"] == "pending_charge":
            await commit_charge(self.redis, self.billing, key, state)
            state["status"] = "completed"
        return {
            "text": state["text"],
            "model": job.model,
            "duration_sec": state["duration_sec"],
            "segments": state["segments"],
        }


def _same_duration(cached: Any, requested: float) -> bool:
    return (
        type(cached) in {int, float}
        and math.isfinite(cached)
        and math.isclose(cached, requested, rel_tol=0, abs_tol=1e-9)
    )


def _validated_segments(raw: Any, text: str, duration: float) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 0 < len(raw) <= 20_000:
        raise VideoSttFailure("protocol")
    segments: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            raise VideoSttFailure("protocol")
        start, end, value = row.get("t_sec"), row.get("end_sec"), row.get("text")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or not 0 <= start <= end <= duration + 1
            or not isinstance(value, str)
            or not value.strip()
            or (segments and start < segments[-1]["t_sec"])
        ):
            raise VideoSttFailure("protocol")
        segments.append({"t_sec": start, "end_sec": end, "text": value.strip()})
    if " ".join(text.split()) != " ".join(" ".join(row["text"] for row in segments).split()):
        raise VideoSttFailure("protocol")
    return segments
