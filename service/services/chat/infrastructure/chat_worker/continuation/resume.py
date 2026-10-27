"""Resolve a durable child inside the worker lease, never from broker transcript data."""

import json
import math
import time
from dataclasses import replace
from typing import Any
from uuid import UUID

from service.infrastructure import workspace_client
from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionRefusal,
)
from service.services.chat.domain.human_questions.resume import RESUME_JOB_KEY, QuestionResume
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerRunRequest
from service.services.chat.persistence.human_questions.repository import HumanQuestionRepository

RESUME_FRAME_KEY = "_human_question_resume_v1"


async def hydrate_question_resume(
    request: WorkerRunRequest, *, connector: Any, config: Any, session: Any
) -> WorkerRunRequest:
    marker = (request.session_data or {}).get(RESUME_JOB_KEY)
    if marker is None:
        return request
    if (
        marker != request.job_id
        or getattr(getattr(config, "human_questions", None), "enabled", False) is not True
    ):
        raise HumanQuestionError("human_question_unavailable")
    try:
        user_id, thread_id, job_id = (
            UUID(str(request.user_id)),
            UUID(request.thread_id),
            UUID(request.job_id),
        )
    except (ValueError, TypeError, AttributeError):
        raise HumanQuestionError("human_question_unavailable") from None
    try:
        resumed = await HumanQuestionRepository(connector).load_resume(
            user_id, thread_id, job_id, session=session
        )
    except Exception:
        # Unknown storage is not a rejected continuation or a terminal job. The
        # outbox can redeliver this SAME child before its first execution claim.
        raise JobStateUnavailable("Question state unavailable") from None
    if isinstance(resumed, QuestionRefusal):
        raise HumanQuestionError(resumed.code)
    if not isinstance(resumed, QuestionResume):
        raise HumanQuestionError("human_question_unavailable")
    if resumed.cost is None or resumed.cost.state not in {"accepted", "not_required"}:
        raise JobStateUnavailable("Question cost decision unavailable")
    target_key = "_ide_context" if resumed.surface == "ide" else "_document_context"
    return replace(
        request,
        text=resumed.text,
        selected_model=resumed.model,
        question_resume=resumed,
        session_data={"session_id": request.thread_id, target_key: json.loads(resumed.target_json)},
        route_override="general",
        input_type="text",
        web_search=False,
        deep_research=False,
        file_context="",
        attachments=None,
        memory_enabled=False,
        ldr_model=None,
        ldr_strategy=None,
        multi_intent=False,
        planning=False,
        persona_ids=None,
    )


async def _document_binding(redis: Any, request: WorkerRunRequest) -> dict:
    state, ref = await workspace_client.read_binding_state(redis, request.thread_id)
    try:
        expiry = float((ref or {}).get("expires_at") or 0)
        valid = math.isfinite(expiry) and expiry > time.time()
    except (ValueError, TypeError):
        valid = False
    if state != "ready" or not ref or str(ref.get("user_id")) != request.user_id or not valid:
        raise HumanQuestionError("human_question_binding_changed")
    return ref


async def build_question_resume_env(
    request: WorkerRunRequest, *, redis: Any, connector: Any
) -> dict:
    from service.services.chat.application.documents.context import validate_document_context
    from service.services.chat.domain.documents.context import DocumentContext
    from service.services.chat.infrastructure.chat_worker.engine_env import build_engine_env

    resumed = request.question_resume
    if resumed is None:
        raise HumanQuestionError("human_question_unavailable")
    data = request.session_data or {}
    binding = None
    if resumed.surface == "pdf":
        before = await _document_binding(redis, request)
        data["_document_context"] = await validate_document_context(
            redis,
            request.thread_id,
            str(request.user_id),
            {
                key: value
                for key, value in data["_document_context"].items()
                if key in DocumentContext.model_fields
            },
        )
        binding = await _document_binding(redis, request)
        if binding["workspace_id"] != before["workspace_id"]:
            raise HumanQuestionError("human_question_binding_changed")
    env = await build_engine_env(
        redis,
        request.thread_id,
        request.user_id,
        [],
        session_data=data,
        agent_run_id=request.run_id,
        pg_connector=connector,
        existing_document_binding=binding,
    )
    ref = env.get("workspace_ref")
    if not isinstance(ref, dict) or not ref.get("coordination_capability"):
        raise HumanQuestionError("human_question_unavailable")
    ref["human_questions_enabled"] = True
    ref[RESUME_FRAME_KEY] = {"model": resumed.model, "messages": json.loads(resumed.messages_json)}
    return env
