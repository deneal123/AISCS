"""One private addressable command request; no automatic POST retries."""

import asyncio
from dataclasses import asdict


async def command_request(client, owner, binding, record, action, capability, limits, **fields):
    async with asyncio.timeout(50):
        return await client._client.request_json(
            "POST",
            f"/workspaces/{binding.workspace_id}/ide/commands",
            timeout=50,
            json_body={
                "user_id": owner.user_id,
                "token": binding.token,
                "task_capability": capability,
                "operation_id": str(record.operation_id),
                "action": action,
                "engine_id": record.engine_id,
                "supervisor": record.supervisor,
                "source_revision": record.source_revision,
                "limits": asdict(limits),
                **fields,
            },
        )
