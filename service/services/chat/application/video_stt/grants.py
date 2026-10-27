"""Single owned-job authorization for the private local transcription bridge."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any
from uuid import UUID

from service.infrastructure.cache.manager import call_redis
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.chat.application.video_stt.execution import (
    AuthorizedVideoSttJob,
    VideoSttFailure,
)
from service.services.chat.application.workspace_collaboration import (
    WorkspaceCollaborationStore,
    verify_capability,
)
from service.settings import config

GRANT_TTL_SEC = 1800


def _key(token: str) -> str:
    return "video:stt:grant:" + hashlib.sha256(token.encode()).hexdigest()


async def mint_video_stt_grant(
    redis: Any,
    *,
    owner_id: str,
    task_id: str,
    thread_id: str,
    capability: str,
    confirmed: bool,
) -> str:
    """Called by the worker, never exposed as a browser mint endpoint."""
    if not confirmed or not all((owner_id, task_id, thread_id, capability)) or redis is None:
        raise VideoSttFailure("forbidden")
    verify_capability(capability, required_role="agent")
    UUID(owner_id)
    token = secrets.token_urlsafe(32)
    await call_redis(
        redis,
        "set",
        _key(token),
        json.dumps(
            {
                "owner_id": owner_id,
                "task_id": task_id,
                "thread_id": thread_id,
                "capability": capability,
                "model": runtime_settings.get_agents(
                    "whisper_default_model", config.agents.whisper_default_model
                ),
                # A linked video can differ from the interface/upload language.
                # Detect speech; do not translate an English source into Russian.
                "language": "auto",
            },
            separators=(",", ":"),
        ),
        ex=GRANT_TTL_SEC,
        nx=True,
    )
    return token


async def authorize_video_stt(
    redis: Any,
    repository: Any,
    *,
    token: str,
    duration_limit_sec: float,
) -> AuthorizedVideoSttJob:
    if redis is None or not 32 <= len(token) <= 128:
        raise VideoSttFailure("forbidden")
    raw = await call_redis(redis, "get", _key(token))
    if not raw:
        raise VideoSttFailure("forbidden")
    binding = json.loads(raw)
    owner_id = UUID(binding["owner_id"])
    job = await repository.fetch_job_by_task_id(binding["task_id"], owner_id)
    if (
        job is None
        or job.user_id != owner_id
        or job.type != ServiceType.CHAT
        or job.status != ProcessingStatus.PROCESSING
        or str((job.payload or {}).get("thread_id") or "") != binding["thread_id"]
    ):
        raise VideoSttFailure("forbidden")
    capability = verify_capability(binding["capability"], required_role="agent")
    store = WorkspaceCollaborationStore(
        redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
    )
    await store.agent_safe_boundary(capability)
    return AuthorizedVideoSttJob(
        str(owner_id), str(job.id), binding["model"], binding["language"], duration_limit_sec
    )
