import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.video_stt.execution import (
    AuthorizedVideoSttJob,
    VideoSttExecutor,
    VideoSttFailure,
)


class PrivateRedis:
    def __init__(self):
        self.values = {}
        self.sorted_sets = {}
        self.expiries = {}

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expiries[key] = ex
        return True

    async def get(self, key):
        return self.values.get(key)

    async def eval(self, script, count, *args):
        if count == 1:
            key, token = args
            if self.values.get(key) == token:
                self.values.pop(key)
            return
        key, pending, index = args[:3]
        if "redis.call('zadd'" in script:
            body, envelope, ttl, score = args[3:]
            await self.set(key, body, ex=ttl)
            await self.set(pending, envelope)
            await self.zadd(index, {pending: score})
        else:
            if key in self.values:
                state = json.loads(self.values[key])
                state["status"] = "completed"
                self.values[key] = json.dumps(state)
            self.values.pop(pending, None)
            await self.zrem(index, pending)

    async def zadd(self, key, values):
        self.sorted_sets.setdefault(key, {}).update(values)

    async def zrange(self, key, start, end):
        values = self.sorted_sets.get(key, {})
        return sorted(values, key=values.get)[start : end + 1]

    async def zrem(self, key, member):
        self.sorted_sets.get(key, {}).pop(member, None)


@pytest.fixture
def setup(monkeypatch):
    return build_executor(monkeypatch)


def build_executor(monkeypatch):
    monkeypatch.setattr(
        "service.services.chat.application.video_stt.execution.whisper_transcription_credits",
        lambda duration, model: (int(duration), duration * 0.003),
    )
    billing = SimpleNamespace(
        reserve=AsyncMock(return_value="reservation"),
        charge=AsyncMock(return_value={}),
        release_reservation=AsyncMock(),
    )
    whisper = SimpleNamespace(
        enabled=True,
        transcribe=AsyncMock(
            return_value={
                "text": "private transcript",
                "duration_sec": 30,
                "model": "base",
                "segments": [{"t_sec": 0, "end_sec": 30, "text": "private transcript"}],
            }
        ),
    )
    job = AuthorizedVideoSttJob("owner", "job", "base", "en", 60)
    return VideoSttExecutor(PrivateRedis(), billing, whisper), job, billing, whisper


@pytest.mark.asyncio
async def test_replay_reuses_transcript_and_charge(setup):
    executor, job, billing, whisper = setup
    first = await executor.execute(job, b"audio")
    assert await executor.execute(job, b"audio") == first
    whisper.transcribe.assert_awaited_once_with(
        b"audio", model="base", language="en", max_duration_sec=60, include_segments=True
    )
    billing.reserve.assert_awaited_once_with("owner", credits=60, ttl_seconds=900)
    billing.charge.assert_awaited_once()
    args = billing.charge.call_args.kwargs
    assert args["credits"] == 30
    assert args["reservation_id"] == "reservation"
    assert "private transcript" not in str(args)


@pytest.mark.asyncio
async def test_charge_recovery_does_not_repeat_stt(setup):
    executor, job, billing, whisper = setup
    billing.charge.side_effect = [RuntimeError("private marker"), {}]
    with pytest.raises(VideoSttFailure, match="unavailable") as exc:
        await executor.execute(job, b"audio")
    assert "private marker" not in str(exc.value)
    result = await executor.execute(job, b"audio")
    assert result["text"] == "private transcript"
    whisper.transcribe.assert_awaited_once()
    assert billing.charge.await_args_list[0] == billing.charge.await_args_list[1]
    billing.release_reservation.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_tolerates_redis_cjson_rounding_only(setup):
    from service.services.chat.application.video_stt.settlement import journal_key

    executor, job, billing, whisper = setup
    job = replace(job, duration_limit_sec=60.12345678901234)
    first = await executor.execute(job, b"audio")
    key = journal_key(job.owner_id, job.job_id)
    state = json.loads(executor.redis.values[key])
    state["duration_limit_sec"] = float(format(job.duration_limit_sec, ".14g"))
    executor.redis.values[key] = json.dumps(state)
    assert await executor.execute(job, b"audio") == first
    with pytest.raises(VideoSttFailure, match="intent_conflict"):
        await executor.execute(
            replace(job, duration_limit_sec=job.duration_limit_sec + 1e-6), b"audio"
        )
    whisper.transcribe.assert_awaited_once()
    billing.charge.assert_awaited_once()


@pytest.mark.parametrize("value", [None, True, "60", float("nan"), float("inf")])
def test_cached_duration_rejects_invalid_numbers(value):
    from service.services.chat.application.video_stt.execution import _same_duration

    assert not _same_duration(value, 60)


@pytest.mark.asyncio
async def test_insufficient_reservation_never_calls_whisper(setup):
    executor, job, billing, whisper = setup
    billing.reserve.return_value = None
    with pytest.raises(VideoSttFailure, match="insufficient_credits"):
        await executor.execute(job, b"audio")
    whisper.transcribe.assert_not_awaited()
    billing.charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_execution_is_not_automatically_retried(setup):
    executor, job, billing, whisper = setup
    whisper.transcribe.side_effect = RuntimeError("secret provider body")
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await executor.execute(job, b"audio")
    with pytest.raises(VideoSttFailure, match="interrupted"):
        await executor.execute(job, b"audio")
    whisper.transcribe.assert_awaited_once()
    billing.release_reservation.assert_awaited_once_with("reservation", user_id="owner")
    billing.charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_with_changed_audio_is_rejected(setup):
    executor, job, billing, whisper = setup
    await executor.execute(job, b"audio")
    with pytest.raises(VideoSttFailure, match="intent_conflict"):
        await executor.execute(job, b"other")
    whisper.transcribe.assert_awaited_once()
    billing.charge.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"model": "large"}, {"duration_limit_sec": 90}])
async def test_changed_request_cannot_create_second_charge_for_same_job(setup, changes):
    executor, job, billing, whisper = setup
    await executor.execute(job, b"audio")
    with pytest.raises(VideoSttFailure, match="intent_conflict"):
        await executor.execute(replace(job, **changes), b"audio")
    whisper.transcribe.assert_awaited_once()
    billing.charge.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [True, float("nan"), 0, 61])
async def test_invalid_whisper_duration_not_charged(setup, duration):
    executor, job, billing, whisper = setup
    whisper.transcribe.return_value["duration_sec"] = duration
    with pytest.raises(VideoSttFailure, match="protocol"):
        await executor.execute(job, b"audio")
    billing.charge.assert_not_awaited()
    billing.release_reservation.assert_awaited_once()


@pytest.mark.asyncio
async def test_concurrent_request_and_cancel_do_not_repeat_whisper(setup):
    executor, job, billing, whisper = setup
    started = asyncio.Event()
    hold = asyncio.Event()

    async def transcribe(*args, **kwargs):
        started.set()
        await hold.wait()

    whisper.transcribe.side_effect = transcribe
    task = asyncio.create_task(executor.execute(job, b"audio"))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        with pytest.raises(VideoSttFailure, match="busy"):
            await executor.execute(job, b"audio")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    with pytest.raises(VideoSttFailure, match="interrupted"):
        await executor.execute(job, b"audio")
    whisper.transcribe.assert_awaited_once()
    billing.charge.assert_not_awaited()
    billing.release_reservation.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_stt_timeout_is_bounded_and_not_retried(setup, monkeypatch):
    executor, job, billing, whisper = setup
    monkeypatch.setattr(
        "service.services.chat.application.video_stt.execution.TRANSCRIBE_TIMEOUT_SEC", 0.01
    )
    hold = asyncio.Event()

    async def transcribe(*args, **kwargs):
        await hold.wait()

    whisper.transcribe.side_effect = transcribe
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await executor.execute(job, b"audio")
    with pytest.raises(VideoSttFailure, match="interrupted"):
        await executor.execute(job, b"audio")
    whisper.transcribe.assert_awaited_once()
    billing.charge.assert_not_awaited()
    billing.release_reservation.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "segments",
    [
        [],
        None,
        [{"t_sec": 0, "end_sec": 1, "text": "invented"}],
        [{"t_sec": True, "end_sec": 30, "text": "private transcript"}],
        [{"t_sec": 0, "end_sec": 32, "text": "private transcript"}],
    ],
)
async def test_invalid_cues_not_billed_or_turned_into_fabricated_timestamps(setup, segments):
    executor, job, billing, whisper = setup
    whisper.transcribe.return_value["segments"] = segments
    with pytest.raises(VideoSttFailure, match="protocol"):
        await executor.execute(job, b"audio")
    billing.charge.assert_not_awaited()
