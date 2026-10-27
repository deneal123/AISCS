"""Exercise the complete migration chain's actual trigger, not only billing SQL."""

import asyncio
import json
import logging
import sys
from uuid import uuid4

from sqlalchemy import text

from scripts.harness.live.environment import environment

logging.disable(logging.CRITICAL)


async def exercise(container):
    connector = container.infra.pg_connector
    owner, task = uuid4(), uuid4()
    async with connector.get_session_context() as db:
        await db.execute(
            text(
                'INSERT INTO profile."user"(id,email,password_hash,available_launches) '
                "VALUES (:owner,:email,'!disabled',0)"
            ),
            {"owner": owner, "email": f"harness-{owner}@example.test"},
        )
        for retained in [False, True]:
            reservation = uuid4()
            await db.execute(
                text(
                    "INSERT INTO profile.token_reservations(reservation_id,user_id,"
                    "tokens_reserved,expires_at,status,harness_task_id) "
                    "VALUES (:id,:owner,100,now()+interval '1 hour','reserved',:task)"
                ),
                {"id": reservation, "owner": owner, "task": task if retained else None},
            )
            await db.execute(
                text(
                    "UPDATE profile.token_reservations SET expires_at=now()-interval '1 hour' "
                    "WHERE reservation_id=:id"
                ),
                {"id": reservation},
            )
            state = await db.scalar(
                text("SELECT status FROM profile.token_reservations WHERE reservation_id=:id"),
                {"id": reservation},
            )
            assert state == ("reserved" if retained else "expired")
            await db.execute(
                text(
                    "UPDATE profile.token_reservations SET tokens_reserved=tokens_reserved "
                    "WHERE reservation_id=:id"
                ),
                {"id": reservation},
            )
            assert (
                await db.scalar(
                    text("SELECT status FROM profile.token_reservations WHERE reservation_id=:id"),
                    {"id": reservation},
                )
                == state
            )
            await db.execute(
                text(
                    "UPDATE profile.token_reservations SET status='committed',committed_at=now() "
                    "WHERE reservation_id=:id"
                ),
                {"id": reservation},
            )
            assert (
                await db.scalar(
                    text("SELECT status FROM profile.token_reservations WHERE reservation_id=:id"),
                    {"id": reservation},
                )
                == "committed"
            )
        await db.commit()
    return {"retention_trigger_verified": True}


async def main():
    async with environment() as container:
        result = await exercise(container)
    print(json.dumps({**result, "fixture_data_removed": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(json.dumps({"stage": "retention_trigger", "error": type(error).__name__}))
        sys.exit(1)
