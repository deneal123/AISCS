"""Internal exact-fence cleanup for an agent write, without waiting for lease TTL."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from service.composition.state import get_optional_redis_client
from service.services.chat.application.workspace_collaboration import (
    CollaborationError,
    CollaborationForbidden,
    WorkspaceCollaborationStore,
    verify_capability,
)
from service.services.chat.presentation.routers.workspace_coordination import (
    _authenticated_payload,
    _error,
)

router = APIRouter(prefix="/internal/workspace-coordination", tags=["internal"])


class ReleasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str = Field(min_length=16, max_length=2048)
    workspace_id: str = Field(min_length=1, max_length=128)
    path: str = Field(min_length=1, max_length=1024)
    fence: int = Field(ge=1)


@router.post("/ide/release")
async def release(
    request: Request,
    payload: ReleasePayload,
    redis: Annotated[Any, Depends(get_optional_redis_client)],
    timestamp: Annotated[str | None, Header(alias="X-Workspace-Timestamp")] = None,
    signature: Annotated[str | None, Header(alias="X-Workspace-Signature")] = None,
):
    await _authenticated_payload(request, timestamp, signature)
    try:
        capability = verify_capability(payload.capability, required_role="agent")
        if capability.workspace_id != payload.workspace_id:
            raise CollaborationForbidden("workspace mismatch")
        store = WorkspaceCollaborationStore(
            redis, workspace_id=capability.workspace_id, expires_at=capability.expires_at
        )
        return {"released": await store.release_lease(capability, payload.path, payload.fence)}
    except CollaborationError as error:
        raise _error(error) from error
