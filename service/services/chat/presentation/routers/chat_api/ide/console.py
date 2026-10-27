"""Private console bodies: current profile owns every read and command."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from service.composition.state import get_app_container, get_optional_redis_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.ide.console import IdeConsoleService
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.application.workspace_collaboration import CollaborationError
from service.services.chat.domain.ide.console import CommandInput, CommandReceipt, ConsoleError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.persistence.harness.commands.history import history
from service.services.chat.presentation.routers.chat_api.ide.edits import _edit
from service.services.chat.presentation.routers.chat_api.ide.runtime import get_ide_runtime
from service.services.files.presentation.routers.files_api.private_route import PrivateFileRoute
from service.shared.security.auth_checker import check_auth


class ConsoleRoute(PrivateFileRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_validation(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Never echo invalid command text or body fields in errors.
                return JSONResponse(
                    status_code=422,
                    content={"detail": {"code": "ide_console_invalid"}},
                    headers={
                        "Cache-Control": "private, no-store",
                        "Pragma": "no-cache",
                        "Vary": "Cookie, Authorization",
                    },
                )

        return private_validation


router = APIRouter(tags=["ide-console"], route_class=ConsoleRoute)


def get_console(
    runtime: Annotated[IdeRuntimeService, Depends(get_ide_runtime)],
    redis: Annotated[Any, Depends(get_optional_redis_client)],
) -> IdeConsoleService:
    return IdeConsoleService(runtime, redis)


async def respond(operation):
    try:
        return await _edit(operation)
    except ConsoleError as error:
        code = error.code
        status = 409 if code == "ide_console_intent_conflict" else 503
        raise HTTPException(status, detail={"code": code, "message": code}) from None
    except CollaborationError:
        raise HTTPException(
            409, detail={"code": "ide_console_blocked", "message": "ide_console_blocked"}
        ) from None


@router.post("/{thread_id}/ide/repositories/{repository_id}/console", response_model=CommandReceipt)
async def execute(
    thread_id: UUID,
    repository_id: UUID,
    payload: CommandInput,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeConsoleService, Depends(get_console)],
    session: Annotated[str | None, Header(alias="X-Workspace-Session")] = None,
):
    return await respond(
        service.execute(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id), payload, session
        )
    )


@router.get(
    "/{thread_id}/ide/repositories/{repository_id}/console/{execution_id}",
    response_model=CommandReceipt,
)
async def status(
    thread_id: UUID,
    repository_id: UUID,
    execution_id: UUID,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeConsoleService, Depends(get_console)],
):
    return await respond(
        service.status(
            RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id), execution_id
        )
    )


@router.get("/{thread_id}/ide/repositories/{repository_id}/agent-commands")
async def agent_commands(
    thread_id: UUID,
    repository_id: UUID,
    request: Request,
    generation: Annotated[str, Query(pattern=r"^[a-f0-9]{64}$")],
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: Annotated[IdeConsoleService, Depends(get_console)],
):
    scope = RepositoryScope(thread_id, UUID(str(profile.user_id)), repository_id)
    await respond(service.runtime._check_owner(scope))
    return await history(get_app_container(request).infra.pg_connector, scope, generation)
