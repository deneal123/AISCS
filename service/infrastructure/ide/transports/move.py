"""No-retry owned move; closed acknowledgement, paths stay in protected bodies."""

import asyncio
from typing import Any
from uuid import UUID

import httpx

from service.infrastructure.sidecar import SidecarError
from service.services.chat.domain.ide.edits import EDIT_ERRORS, IdeEditError
from service.services.chat.domain.ide.runtime import WorkspaceBinding


async def move_repository(
    client: Any,
    user_id: UUID,
    binding: WorkspaceBinding,
    *,
    path: str,
    destination: str,
    expected_digest: str | None,
    capability: str,
    fence: int,
    destination_fence: int,
) -> dict[str, Any]:
    try:
        async with asyncio.timeout(12):
            result = await client._client.request_json(
                "POST",
                f"/workspaces/{binding.workspace_id}/ide/move",
                timeout=12,
                json_body=dict(
                    user_id=str(user_id),
                    token=binding.token,
                    path=path,
                    destination=destination,
                    expected_digest=expected_digest,
                    coordination_capability=capability,
                    coordination_fence=fence,
                    destination_fence=destination_fence,
                ),
            )
        if (
            type(result) is not dict
            or set(result) != {"moved", "path", "moved_from", "size"}
            or result["moved"] is not True
            or result["path"] != destination
            or result["moved_from"] != path
            or type(result["size"]) is not int
            or result["size"] < 0
        ):
            raise IdeEditError("ide_write_unconfirmed")
        return result
    except SidecarError as error:
        raise IdeEditError(
            error.code if error.code in EDIT_ERRORS else "ide_write_unconfirmed"
        ) from None
    except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
        raise IdeEditError("ide_write_unconfirmed") from None
