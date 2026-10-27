"""One attempt through the existing isolated workspace exec boundary."""

import asyncio

from service.services.chat.domain.ide.console import CommandResult


async def execute_repository(client, user_id, binding, *, command, capability):
    async with asyncio.timeout(125):
        result = await client._client.request_json(
            "POST",
            f"/workspaces/{binding.workspace_id}/exec",
            timeout=125,
            json_body={
                "user_id": str(user_id),
                "token": binding.token,
                "command": command,
                "coordination_capability": capability,
            },
        )
    return CommandResult.model_validate(result).model_dump()
