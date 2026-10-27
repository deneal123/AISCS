"""Opt-in dev-only STT probe; runtime runner supplies private input on stdin.

Two synthetic owned jobs: private HTTP replay and a test-boundary charge failure.
No shared service is stopped; no provider, pricing or production state is changed.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import sys
import uuid
import wave

import httpx

from service.infrastructure.cache.manager import RedisManager
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.workspace_client import ensure_workspace_explicit, release_workspace
from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.billing.application.billing_service import BillingService
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.application.video_stt.execution import VideoSttExecutor, VideoSttFailure
from service.services.chat.application.video_stt.grants import (
    authorize_video_stt,
    mint_video_stt_grant,
)
from service.services.chat.application.video_stt.settlement import (
    charge_key,
    journal_key,
    reconcile_pending_video_stt,
)
from service.services.chat.application.workspace_collaboration import mint_capability
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    WhisperLocalTranscriber,
    whisper_transcription_credits,
)
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.profile.persistence.profile_repository import ProfileRepository
from service.settings import config


class ChargeFailureOnce:
    def __init__(self, billing):
        self.billing = billing
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.billing, name)

    async def charge(self, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic charge outage")
        return await self.billing.charge(*args, **kwargs)


class CountingWhisper(WhisperLocalTranscriber):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def transcribe(self, *args, **kwargs):
        self.calls += 1
        return await super().transcribe(*args, **kwargs)


async def main(wire):
    if wire.get("opt_in") is not True:
        raise ValueError("opt_in_required")
    audio = base64.b64decode(wire["audio"], validate=True)
    with wave.open(io.BytesIO(audio)) as wav:
        duration = wav.getnframes() / wav.getframerate()
    if not 1 < duration < 30:
        raise ValueError("fixture_duration")
    db = PgConnector(config.pg, force_new=True)
    manager = RedisManager(config.redis)
    redis = manager.get_client()
    jobs = JobRepository(db)
    billing = BillingService(BillingRepository(db), config.billing)
    thread = None
    created = []
    bindings = []
    stages = {"stage": "fixture"}
    async with httpx.AsyncClient(
        base_url="http://localhost:8000",
        cookies={"auth_token": wire["token"]},
        timeout=240,
        trust_env=False,
    ) as http:
        try:
            user = await ProfileRepository(db).fetch_user_by_email(
                "s38-video-acceptance@example.com"
            )
            assert user is not None
            from service.shared.security.auth_validation import AuthValidator

            assert str(AuthValidator(config.auth).validate_http_jwt(wire["token"]).user_id) == str(
                user.id
            )
            profile = await http.get("/api/profile/me")
            assert profile.status_code == 200
            before = (await billing.get_balance(str(user.id))).total
            response = await http.post(
                "/api/chats/", json={"title": "S38 synthetic local STT runtime"}
            )
            assert response.status_code == 201
            thread = response.json()["thread_id"]
            ref = await ensure_workspace_explicit(redis, thread, str(user.id))
            assert ref and ref.get("coordination_capability") is None
            capability = mint_capability(
                ref["workspace_id"],
                role="agent",
                actor_seed="s38-synthetic-stt",
                expires_at=ref["expires_at"],
                run_id=thread,
            )

            async def prepare():
                task = "s38-local-stt-" + uuid.uuid4().hex
                job = await jobs.create_job(
                    JobLogic(
                        user_id=user.id,
                        type=ServiceType.CHAT,
                        status=ProcessingStatus.PROCESSING,
                        payload={
                            "thread_id": thread,
                            "celery_task_id": task,
                            "synthetic_stt": True,
                        },
                    )
                )
                created.append(job)
                grant = await mint_video_stt_grant(
                    redis,
                    owner_id=str(user.id),
                    task_id=task,
                    thread_id=thread,
                    capability=capability,
                    confirmed=True,
                )
                authorized = await authorize_video_stt(
                    redis,
                    jobs,
                    token=grant,
                    duration_limit_sec=duration + 1,
                )
                assert whisper_transcription_credits(duration + 1, authorized.model)[0] <= 2000
                bindings.append((job, grant, authorized))
                return job, grant, authorized

            stages["stage"] = "private_http"
            _, grant, authorized = await prepare()
            endpoint = "/internal/video-stt/transcribe"
            headers = {
                "Authorization": "Bearer " + grant,
                "Content-Type": "application/octet-stream",
            }
            first = await http.post(
                endpoint,
                params={"duration_limit_sec": duration + 1},
                headers=headers,
                content=audio,
            )
            stages["private_http_status"] = first.status_code
            stages["model"] = authorized.model
            if first.status_code != 200:
                code = first.json().get("error", {}).get("code")
                stages["failure_code"] = (
                    code
                    if code
                    in {
                        "unavailable",
                        "protocol",
                        "forbidden",
                        "interrupted",
                        "insufficient_credits",
                    }
                    else "unknown"
                )
            assert first.status_code == 200
            result = first.json()
            assert result["segments"] and result["model"] == authorized.model
            normalized = " ".join(result["text"].lower().split())
            stages["speech_checks"] = {
                "test": "test" in normalized,
                "negation": "not" in normalized,
                "amount": "twenty" in normalized or "25" in normalized,
            }
            assert all(stages["speech_checks"].values())
            replay = await http.post(
                endpoint,
                params={"duration_limit_sec": duration + 1},
                headers=headers,
                content=audio,
            )
            stages["replay_http_status"] = replay.status_code
            if replay.status_code != 200:
                code = replay.json().get("error", {}).get("code")
                stages["replay_failure"] = (
                    code
                    if code
                    in {"intent_conflict", "unavailable", "forbidden", "interrupted", "busy"}
                    else "unknown"
                )
            assert replay.status_code == 200
            recovered = replay.json()
            assert recovered["text"] == result["text"]
            assert recovered["model"] == result["model"]
            assert recovered["segments"] == result["segments"]
            assert abs(recovered["duration_sec"] - result["duration_sec"]) < 1e-9
            stages.update(
                http_replay=True,
                segment_count=len(result["segments"]),
                speech_fixture_checks=True,
                model=authorized.model,
            )

            stages["stage"] = "settlement"
            job, grant, authorized = await prepare()
            whisper = CountingWhisper()
            executor = VideoSttExecutor(redis, ChargeFailureOnce(billing), whisper)
            try:
                await executor.execute(authorized, audio)
            except VideoSttFailure as error:
                assert error.code == "unavailable"
            else:
                raise AssertionError("charge_outage_not_exercised")
            key = journal_key(authorized.owner_id, authorized.job_id)
            assert await redis.exists(charge_key(key))
            # Expire the content cache/grant and terminate the originating owned job.
            # Financial recovery must not require them or another Whisper call.
            await redis.delete(key)
            from service.services.chat.application.video_stt.grants import _key

            await redis.delete(_key(grant))
            await jobs.update_job_status(
                job.model_copy(update={"status": ProcessingStatus.FAILURE})
            )
            settled = await reconcile_pending_video_stt(redis, billing, jobs)
            assert settled["settled"] >= 1 and not await redis.exists(charge_key(key))
            assert whisper.calls == 1
            await reconcile_pending_video_stt(redis, billing, jobs)
            stages.update(settlement_after_expiry=True, recovery_whisper_calls=whisper.calls)
            async with db.get_session_context() as session:
                # Check exact owned idempotency keys, not aggregate account activity.
                from sqlalchemy import text

                keys = [journal_key(str(user.id), str(row.id)) for row in created]
                charges = (
                    (
                        await session.execute(
                            text(
                                "SELECT metadata FROM profile.billing_events WHERE user_id=:owner "
                                "AND metadata->>'idempotency_key' IN (:first,:second)"
                            ),
                            {"owner": user.id, "first": keys[0], "second": keys[1]},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(charges) == 2 and all(c.get("kind") == "transcription" for c in charges)
                assert all(c.get("engine") == "local" for c in charges)
                spent = sum(c["from_subscription"] + c["from_topup"] for c in charges)
            after = (await billing.get_balance(str(user.id))).total
            assert before - after == spent
            stages.update(
                charge_count=2,
                spent=spent,
                balance_before=before,
                balance_after=after,
                llm_calls=0,
                status="passed",
            )
        except Exception:
            stages["status"] = "failed"
        finally:
            for row in created:
                current = await jobs.fetch_job_by_id(row.id, row.user_id)
                if current and current.status == ProcessingStatus.PROCESSING:
                    await jobs.update_job_status(
                        current.model_copy(
                            update={
                                "status": ProcessingStatus.SUCCESS
                                if stages.get("status") == "passed"
                                else ProcessingStatus.FAILURE
                            }
                        )
                    )
            from service.services.chat.application.video_stt.grants import _key

            for _row, grant, authorized in bindings:
                await redis.delete(_key(grant), journal_key(authorized.owner_id, authorized.job_id))
            if thread:
                await release_workspace(redis, thread)
            stages["fixture_jobs_finalized"] = True
            await manager.close()
            await db.close()
    return stages


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        report = asyncio.run(main(json.load(sys.stdin)))
    except Exception:
        report = {"status": "failed", "stage": "probe_boundary"}
    print(json.dumps(report))
