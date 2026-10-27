"""Owner-checked review of workspace-private semantic proposals."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from service.composition.state import get_chat_application_service, get_optional_redis_client
from service.infrastructure import workspace_client
from service.models.auth_models import AuthProfile
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.application.documents.proposals import proposal_draft
from service.shared.security.auth_checker import check_auth

router = APIRouter()


@router.get("/{thread_id}/workspace/documents/proposals/{proposal_id}")
async def document_proposal(
    thread_id: str,
    proposal_id: str,
    profile: Annotated[AuthProfile, Depends(check_auth)],
    service: ChatApplicationService = Depends(get_chat_application_service),  # noqa: B008
    redis=Depends(get_optional_redis_client),  # noqa: B008
):
    from service.services.chat.presentation.routers.chat_api.workspace.router import _ref

    ref = await _ref(service, thread_id, str(profile.user_id), redis)
    import re

    if re.fullmatch(r"[a-f0-9]{32}", proposal_id) is None:
        raise HTTPException(status_code=404, detail="document_proposal_not_found")
    result = await workspace_client._call(
        ref, "documents/proposals/read", {"proposal_id": proposal_id}
    )
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="document_proposal_not_found")
    state = await workspace_client.document_authoring_state(ref, path=result["path"])
    project = await workspace_client.document_project_status(ref, path=result["path"])
    if not state or not project:
        raise HTTPException(status_code=404, detail="document_project_not_found")
    proposal = result["proposal"]
    stale = (
        state.get("authoring_version") != proposal.get("base_version")
        or state.get("draft_digest") != proposal.get("draft_digest")
        or project.get("revision") != proposal.get("expected_revision")
    )
    before = state["draft"]
    draft = proposal_draft(before, proposal, stale=stale)
    return {
        "patch_version": proposal.get("patch_version", 1),
        "proposal_id": proposal_id,
        "path": result["path"],
        "stale": stale,
        "expected_revision": proposal["expected_revision"],
        "authoring_version": proposal["base_version"],
        "draft_digest": proposal["draft_digest"],
        "before": before,
        "draft": draft,
    }
