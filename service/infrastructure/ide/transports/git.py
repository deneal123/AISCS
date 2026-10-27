"""Private, non-retrying owned-runtime Git setup transport."""

import asyncio
import base64
from typing import Any
from uuid import UUID

import httpx

from service.infrastructure.ide.transports.git_fetch import branch_name
from service.infrastructure.sidecar import SidecarError
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.runtime import WorkspaceBinding


async def git_repository(
    client: Any,
    user_id: UUID,
    binding: WorkspaceBinding,
    *,
    operation: str,
    capability: str,
    branch: str = "main",
    origin: str = "",
    commit: str = "",
    pack: bytes = b"",
    replace_pristine_starter: bool = False,
) -> dict[str, Any]:
    if type(replace_pristine_starter) is not bool or (
        replace_pristine_starter and operation != "clone"
    ):
        raise IdeEditError("ide_git_invalid")
    try:
        async with asyncio.timeout(32):
            result = await client._client.request_json(
                "POST",
                f"/workspaces/{binding.workspace_id}/ide/git",
                timeout=32,
                json_body=dict(
                    user_id=str(user_id),
                    token=binding.token,
                    operation=operation,
                    coordination_capability=capability,
                    branch=branch,
                    origin=origin,
                    commit=commit,
                    pack=base64.b64encode(pack).decode("ascii"),
                    **({"replace_pristine_starter": True} if replace_pristine_starter else {}),
                ),
            )
        if (
            type(result) is not dict
            or set(result) != {"initialized", "branch"}
            or type(result["initialized"]) is not bool
            or (
                result["branch"] is not None
                and (type(result["branch"]) is not str or not branch_name(result["branch"]))
            )
            or (not result["initialized"] and result["branch"] is not None)
        ):
            raise IdeEditError("ide_git_unconfirmed")
        if operation != "status" and not result["initialized"]:
            raise IdeEditError("ide_git_unconfirmed")
        return result
    except SidecarError as error:
        raise IdeEditError(
            error.code if error.code in EDIT_ERRORS else "ide_git_unconfirmed"
        ) from None
    except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
        raise IdeEditError("ide_git_unconfirmed") from None
