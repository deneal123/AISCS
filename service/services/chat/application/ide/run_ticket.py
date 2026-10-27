"""Short-lived private IDE selection; the socket carries only an opaque handle."""

import json
from uuid import UUID, uuid4

from fastapi import HTTPException

TTL = 120


async def issue_ticket(redis, *, thread_id, user_id, target):
    ticket = str(uuid4())
    if redis is None:
        raise HTTPException(503, "ide_runtime_unavailable")
    await redis.set(
        f"ide:run-target:{ticket}",
        json.dumps(
            {
                "thread_id": str(thread_id),
                "user_id": str(user_id),
                "target": target,
            }
        ),
        ex=TTL,
    )
    return {"target_id": ticket, "expires_in": TTL}


async def read_ticket(redis, *, thread_id, user_id, ticket):
    try:
        if type(ticket) is not str:
            raise ValueError
        canonical = str(UUID(ticket))
        if canonical != ticket or redis is None:
            raise ValueError
        raw = await redis.get(f"ide:run-target:{canonical}")
        value = json.loads(raw or "null")
        if (
            not isinstance(value, dict)
            or value.get("thread_id") != str(thread_id)
            or value.get("user_id") != str(user_id)
        ):
            raise ValueError
        from service.services.chat.domain.ide.agent_context import IdeAgentContext

        return IdeAgentContext.model_validate(value["target"]).model_dump(mode="json")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "ide_agent_context_invalid") from None
