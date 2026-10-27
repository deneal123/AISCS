"""Owned question status/reply/cancel. No model or broker call in HTTP handlers."""

from collections.abc import Awaitable
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from starlette.requests import HTTPConnection

from service.composition.state import get_app_container, get_optional_redis_client
from service.infrastructure import workspace_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.human_questions.service import HumanQuestionService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.human_questions.contracts import HumanQuestionError, QuestionScope
from service.services.chat.domain.human_questions.reply import QuestionReplyInput
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.files import READ_ERRORS, IdeReadError
from service.services.chat.infrastructure.chat_worker.continuation.dispatch import (
    trigger_human_question_dispatch,
)
from service.services.chat.infrastructure.question_budget import QuestionBudget
from service.services.chat.persistence.human_questions.cost import HumanQuestionCostRepository
from service.services.chat.persistence.human_questions.repository import HumanQuestionRepository
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.settings import config
from service.shared.repositories.exceptions import RepositoryError
from service.shared.security.auth_checker import check_auth

router = APIRouter(tags=["human-questions"], route_class=PrivateFileRoute)
PATH = "/{thread_id}/runs/{source_job_id}/questions/{question_id}"


class CancelQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionCostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: UUID
    decision: Literal["accept", "decline", "refresh"]


def failure(status: int, code: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": code})


def get_questions(
    request: HTTPConnection,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
) -> HumanQuestionService:
    if not config.human_questions.enabled:
        raise failure(503, "human_question_unavailable")
    return HumanQuestionService(
        HumanQuestionRepository(get_app_container(request).infra.pg_connector),
        runtime,
        redis,
        budget=QuestionBudget(get_app_container(request).infra.pg_connector, config),
        costs=HumanQuestionCostRepository(get_app_container(request).infra.pg_connector),
    )


async def respond(operation: Awaitable[dict]) -> dict:
    try:
        return await operation
    except HumanQuestionError as error:
        statuses = {
            "human_question_not_found": 404,
            "human_question_invalid": 422,
            "human_question_conflict": 409,
            "human_question_binding_changed": 409,
        }
        code = error.code if error.code in statuses else "human_question_unavailable"
        raise failure(statuses.get(code, 503), code) from None
    except IdeEditError as error:
        raise failure(EDIT_ERRORS[error.code], error.code) from None
    except IdeReadError as error:
        raise failure(READ_ERRORS[error.code], error.code) from None
    except IdeRepositoryNotFound:
        raise failure(404, "human_question_not_found") from None
    except RepositoryError:
        # Includes unknown commit ACK: client must read/retry the SAME intent.
        raise failure(503, "human_question_status_unknown") from None
    except workspace_client.WorkspaceGone:
        raise failure(409, "human_question_binding_changed") from None
    except workspace_client.WorkspaceUnavailable:
        raise failure(503, "human_question_unavailable") from None
    except HTTPException as error:
        # Reuse the existing document validator without exposing arbitrary details.
        statuses = {
            "document_project_not_found": 404,
            "document_context_invalid": 422,
            "source_changed": 409,
        }
        code = error.detail if isinstance(error.detail, str) else ""
        if code not in statuses:
            code = "human_question_unavailable"
        raise failure(statuses.get(code, 503), code) from None


def scope_for(thread_id: UUID, source_job_id: UUID, profile: AuthProfile) -> QuestionScope:
    try:
        return QuestionScope(UUID(str(profile.user_id)), thread_id, source_job_id)
    except (HumanQuestionError, ValueError):
        raise failure(422, "human_question_invalid") from None


@router.get(PATH)
async def read_question(
    thread_id: UUID,
    source_job_id: UUID,
    question_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[HumanQuestionService, Depends(get_questions)],
):
    return await respond(service.read(scope_for(thread_id, source_job_id, profile), question_id))


@router.post(PATH + "/answer")
async def answer_question(
    thread_id: UUID,
    source_job_id: UUID,
    question_id: UUID,
    payload: QuestionReplyInput,
    background_tasks: BackgroundTasks,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[HumanQuestionService, Depends(get_questions)],
):
    result = await respond(
        service.answer(scope_for(thread_id, source_job_id, profile), question_id, payload)
    )
    if result["state"] == "accepted":
        background_tasks.add_task(trigger_human_question_dispatch)
    return result


@router.post(PATH + "/cancel")
async def cancel_question(
    thread_id: UUID,
    source_job_id: UUID,
    question_id: UUID,
    payload: CancelQuestionInput,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[HumanQuestionService, Depends(get_questions)],
):
    return await respond(service.cancel(scope_for(thread_id, source_job_id, profile), question_id))


@router.get(PATH + "/cost")
async def read_question_cost(
    thread_id: UUID,
    source_job_id: UUID,
    question_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[HumanQuestionService, Depends(get_questions)],
):
    return await respond(
        service.read_cost(scope_for(thread_id, source_job_id, profile), question_id)
    )


@router.post(PATH + "/cost")
async def decide_question_cost(
    thread_id: UUID,
    source_job_id: UUID,
    question_id: UUID,
    payload: QuestionCostInput,
    background_tasks: BackgroundTasks,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[HumanQuestionService, Depends(get_questions)],
):
    result = await respond(
        service.decide_cost(
            scope_for(thread_id, source_job_id, profile),
            question_id,
            payload.offer_id,
            payload.decision,
        )
    )
    if result["state"] in {"accepted", "not_required"}:
        background_tasks.add_task(trigger_human_question_dispatch)
    return result
