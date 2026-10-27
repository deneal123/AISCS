"""Remove a retained acceptance fixture only after all effects are resolved."""

import asyncio
import json
import re
import sys

import asyncpg
from sqlalchemy import text

from scripts.harness.live.environment import cleanup_snapshots


async def main(database):
    assert re.fullmatch(r"gpthub_acceptance_[a-f0-9]{24}", database)
    from service.settings import config

    config.pg.db = database
    from service.composition.container import build_container

    container = build_container(config)
    connector = container.infra.pg_connector
    try:
        async with connector.get_session_context() as db:
            owners = (
                await db.execute(text('SELECT email,password_hash FROM profile."user"'))
            ).all()
            assert len(owners) <= 1
            for owner in owners:
                assert re.fullmatch(r"harness-[a-f0-9-]{36}@example\.test", owner.email)
                assert owner.password_hash == "!disabled"
            unresolved = await db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE status IN "
                    "('prepared','dispatched','unknown')) OR EXISTS(SELECT 1 FROM "
                    "profile.harness_grant WHERE state IN ('allocated','dispatched','unknown')) OR "
                    "EXISTS(SELECT 1 FROM profile.harness_operation WHERE command IS NOT NULL AND "
                    "(COALESCE(command->>'cleanup_confirmed','')<>'true' OR "
                    "COALESCE(command->>'state','') NOT IN "
                    "('completed','failed','cancelled'))) OR EXISTS(SELECT 1 FROM "
                    "profile.ide_checkpoint_intent WHERE command_pins<>0)"
                )
            )
            assert unresolved is False, "acceptance_unresolved_effects_preserved"
        await cleanup_snapshots(container)
    finally:
        await connector.close()
        if container.infra.redis_manager:
            await container.infra.redis_manager.close()
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database="postgres",
    )
    try:
        await admin.execute('DROP DATABASE "' + database + '"')
    finally:
        await admin.close()
    return {"terminal_fixture_removed": True, "fixture_data_removed": True}


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(sys.argv[-1]))))
    except BaseException as error:
        print(json.dumps({"stage": "terminal_fixture_cleanup", "error": type(error).__name__}))
        sys.exit(1)
