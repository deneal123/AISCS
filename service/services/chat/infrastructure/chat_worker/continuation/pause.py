"""Private pause -> owned journal + public reference, in the accepted-turn transaction."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionPause,
    QuestionPrompt,
    QuestionRefusal,
    QuestionScope,
    freeze_question_continuation,
    parse_public_question,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.persistence.human_questions.repository import HumanQuestionRepository

PAUSE_KEY = "_human_question_pause_v1"


def prepare_question(request: Any, state: Any, result: dict, reply: str) -> QuestionPause | None:
    raw = result.get(PAUSE_KEY)
    metadata = result.get("metadata") or {}
    if type(metadata) is not dict:
        raise HumanQuestionError()
    if raw is None:
        if (
            metadata.get("awaiting_user")
            or metadata.get("human_question") is not None
            or metadata.get("execution_status") == "waiting_user"
        ):
            raise HumanQuestionError()
        return None
    if (
        type(raw) is not dict
        or set(raw) != {"prompt", "continuation", "workspace_revision"}
        or metadata.get("awaiting_user") is not True
        or metadata.get("execution_status") != "waiting_user"
    ):
        raise HumanQuestionError()
    ref = (state.engine_env or {}).get("workspace_ref") or {}
    if ref.get("human_questions_enabled") is not True:
        raise HumanQuestionError()
    ide, document = ref.get("ide_context"), ref.get("document_context")
    if isinstance(ide, dict) == isinstance(document, dict):
        raise HumanQuestionError()
    target = ide if isinstance(ide, dict) else document
    prompt = QuestionPrompt.parse(raw["prompt"])
    if (
        reply != prompt.prompt
        or type(raw["continuation"]) is not dict
        or raw["continuation"].get("model") != result.get("resolved_model")
    ):
        raise HumanQuestionError()
    scope = QuestionScope(UUID(str(request.user_id)), UUID(request.thread_id), UUID(request.job_id))
    latest = raw["workspace_revision"]
    if latest is not None and (type(latest) is not str or not 0 < len(latest) <= 128):
        raise HumanQuestionError()
    revision = (
        target.get("generation")
        if isinstance(ide, dict)
        else latest or target.get("expected_revision")
    )
    return QuestionPause(
        scope,
        uuid5(scope.source_job_id, "gpthub:human-question:v1"),
        UUID(str(state.execution_attempt_id)),
        "ide" if isinstance(ide, dict) else "pdf",
        UUID(str(target.get("repository_id" if isinstance(ide, dict) else "project_id"))),
        revision,
        prompt,
        ref.get("expires_at"),
        freeze_question_continuation(raw["continuation"], prompt),
    )


async def stage_question(
    pause: QuestionPause, *, repository: Any, session: Any, metadata: dict
) -> None:
    result = await HumanQuestionRepository(repository.connector).stage(pause, session=session)
    if isinstance(result, QuestionRefusal):
        raise JobStateUnavailable("Question checkpoint unavailable")
    metadata["human_question"] = parse_public_question(result)
    metadata["execution_status"] = "waiting_user" if result["state"] == "pending" else "partial"
    metadata.pop("awaiting_user", None)
    metadata.pop("ide_summary", None)


async def verify_question_reference(
    *, request: Any, repository: Any, session: Any, metadata: dict
) -> None:
    raw = metadata.get("human_question")
    if raw is None:
        if metadata.get("execution_status") == "waiting_user":
            raise JobStateUnavailable("Question checkpoint unavailable")
        return
    try:
        expected = parse_public_question(raw)
        scope = QuestionScope(
            UUID(str(request.user_id)), UUID(request.thread_id), UUID(request.job_id)
        )
        question_id = uuid5(scope.source_job_id, "gpthub:human-question:v1")
        if (
            expected["question_id"] != str(question_id)
            or expected["source_job_id"] != request.job_id
        ):
            raise HumanQuestionError()
        current = await HumanQuestionRepository(repository.connector).read_staged(
            scope, question_id, session=session
        )
        # The metadata is a frozen message snapshot, not live answer/expiry state.
        # Compare immutable identity/content; the public read API owns current state.
        if current is None or any(
            current[key] != expected[key]
            for key in expected
            if key not in {"state", "resume_job_id"}
        ):
            raise HumanQuestionError()
    except Exception:
        raise JobStateUnavailable("Question checkpoint unavailable") from None
