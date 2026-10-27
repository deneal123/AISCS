import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.chat.application.video_stt.execution import VideoSttFailure
from service.services.chat.application.video_stt.settlement import (
    INDEX,
    charge_key,
    journal_key,
    reconcile_pending_video_stt,
)
from tests.test_video_stt_executor import build_executor


@pytest.fixture
def setup(monkeypatch):
    return build_executor(monkeypatch)


@pytest.mark.asyncio
async def test_terminal_job_and_expired_transcript_can_still_settle_once(setup):
    executor, original, billing, whisper = setup
    job = replace(original, owner_id=str(uuid4()), job_id=str(uuid4()))
    billing.charge.side_effect = RuntimeError("private database body")
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await executor.execute(job, b"audio")
    key = journal_key(job.owner_id, job.job_id)
    pending = charge_key(key)
    assert executor.redis.expiries[pending] is None
    envelope = json.loads(executor.redis.values[pending])
    assert "text" not in envelope and "segments" not in envelope
    assert "private transcript" not in executor.redis.values[pending]
    executor.redis.values.pop(key)  # the short-lived content cache has expired
    billing.charge.side_effect = None
    owned = SimpleNamespace(type=ServiceType.CHAT, status="FAILURE")
    jobs = SimpleNamespace(fetch_job_by_id=AsyncMock(return_value=owned))
    result = await reconcile_pending_video_stt(executor.redis, billing, jobs)
    assert result == {"examined": 1, "settled": 1, "deferred": 0, "invalid": 0}
    assert await reconcile_pending_video_stt(executor.redis, billing, jobs) == {
        "examined": 0,
        "settled": 0,
        "deferred": 0,
        "invalid": 0,
    }
    whisper.transcribe.assert_awaited_once()
    assert billing.charge.await_args_list[0] == billing.charge.await_args_list[1]
    assert pending not in executor.redis.values
    assert executor.redis.sorted_sets[INDEX] == {}


@pytest.mark.asyncio
async def test_price_changes_after_acceptance_do_not_reprice_recovery(setup, monkeypatch):
    executor, job, billing, whisper = setup
    billing.charge.side_effect = [RuntimeError("down"), {}]
    with pytest.raises(VideoSttFailure):
        await executor.execute(job, b"audio")
    monkeypatch.setattr(
        "service.services.chat.application.video_stt.execution.whisper_transcription_credits",
        lambda *args: (60000, 180),
    )
    await executor.execute(job, b"audio")
    assert billing.charge.await_args_list[0] == billing.charge.await_args_list[1]
    assert billing.charge.call_args.kwargs["credits"] == 30
    whisper.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_crash_after_charge_commit_before_cache_update_is_idempotent(setup):
    executor, original, billing, whisper = setup
    job = replace(original, owner_id=str(uuid4()), job_id=str(uuid4()))
    actual_eval = executor.redis.eval
    failed = False

    async def eval_once(script, *args):
        nonlocal failed
        if "'KEEPTTL'" in script and not failed:
            failed = True
            raise RuntimeError("Redis disconnected after DB commit")
        return await actual_eval(script, *args)

    executor.redis.eval = eval_once
    charged = set()
    actual_charges = []

    async def charge(owner, **kwargs):
        if kwargs["idempotency_key"] in charged:
            return {"idempotent": True}
        charged.add(kwargs["idempotency_key"])
        actual_charges.append(kwargs["credits"])
        return {}

    billing.charge.side_effect = charge
    with pytest.raises(VideoSttFailure, match="unavailable"):
        await executor.execute(job, b"audio")
    jobs = SimpleNamespace(
        fetch_job_by_id=AsyncMock(return_value=SimpleNamespace(type=ServiceType.CHAT))
    )
    assert (await reconcile_pending_video_stt(executor.redis, billing, jobs))["settled"] == 1
    assert actual_charges == [30]
    whisper.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_corrupt_pending_envelope_cannot_charge_another_owner(setup):
    executor, original, billing, whisper = setup
    job = replace(original, owner_id=str(uuid4()), job_id=str(uuid4()))
    billing.charge.side_effect = RuntimeError("down")
    with pytest.raises(VideoSttFailure):
        await executor.execute(job, b"audio")
    key = charge_key(journal_key(job.owner_id, job.job_id))
    envelope = json.loads(executor.redis.values[key])
    envelope["owner_id"] = str(uuid4())
    executor.redis.values[key] = json.dumps(envelope)
    billing.charge.reset_mock()
    jobs = SimpleNamespace(fetch_job_by_id=AsyncMock())
    result = await reconcile_pending_video_stt(executor.redis, billing, jobs)
    assert result["invalid"] == 1
    billing.charge.assert_not_awaited()
    jobs.fetch_job_by_id.assert_not_awaited()
