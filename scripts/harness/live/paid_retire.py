"""Retire only a terminal acceptance runtime, preserving actual paid journal/data."""

import asyncio
import json
import logging
import sys
from uuid import UUID

from sqlalchemy import text

from scripts.harness.live.environment import backend_http
from scripts.harness.live.paid import retire_test_runtime
from scripts.harness.live.paid_archive import archive_sources
from scripts.harness.live.paid_setup import ANCHOR_JOB, paid_environment

logging.disable(logging.CRITICAL)


async def reconcile_invalid_arguments(container, row):
    from service.services.chat.application.harness_capability import HarnessOwner
    from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository

    assert row["active_job_id"] == row["task_id"]
    owner = HarnessOwner(
        task_id=str(row["task_id"]),
        job_id=str(row["active_job_id"]),
        user_id=str(row["user_id"]),
        thread_id=str(row["thread_id"]),
        attempt_id=str(row["execution_attempt_id"]),
        epoch=row["fencing_epoch"],
        project_id=row["admission"]["project_id"],
        generation=row["admission"]["generation"],
    )
    async with container.infra.pg_connector.get_session_context() as db:
        operations = (
            (
                await db.execute(
                    text(
                        "SELECT operation_id,intent FROM profile.harness_operation "
                        "WHERE task_id=:job "
                        "AND status IN ('dispatched','unknown') AND command IS NULL "
                        "AND intent->>'name'='ide_run_command'"
                    ),
                    {"job": row["task_id"]},
                )
            )
            .mappings()
            .all()
        )
    repository = IdeCommandRepository(container.infra.pg_connector)
    for operation in operations:
        # The product repository rechecks current ownership, exact canonical
        # arguments, invalidity and locked absence of any executor record.
        await repository.reject_invalid_command(
            owner, operation["operation_id"], json.loads(operation["intent"]["arguments"])
        )


async def main(job):
    from service.services.chat.domain.ide.runtime import RepositoryScope

    async with paid_environment() as container, backend_http(container):
        async with container.infra.pg_connector.get_session_context() as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT t.*,j.status AS job_status,c.title "
                            "FROM profile.harness_task t "
                            "JOIN profile.user_launch j ON j.id=t.task_id "
                            "JOIN profile.chat_threads c ON c.thread_id=t.thread_id "
                            "AND c.user_id=t.user_id "
                            "WHERE t.task_id=:job AND t.user_id="
                            "(SELECT user_id FROM profile.user_launch WHERE id=:anchor)"
                        ),
                        {"job": job, "anchor": ANCHOR_JOB},
                    )
                )
                .mappings()
                .one()
            )
            assert row["title"] == "Harness: paid GigaChat acceptance"
            assert row["job_status"] == "SUCCESS" and row["settled_credits"] > 0
        await reconcile_invalid_arguments(container, row)
        async with container.infra.pg_connector.get_session_context() as db:
            assert (
                await db.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:job "
                        "AND status IN ('prepared','dispatched','unknown')) OR EXISTS(SELECT 1 "
                        "FROM profile.harness_grant WHERE task_id=:job "
                        "AND state IN ('allocated','dispatched','unknown'))"
                    ),
                    {"job": job},
                )
                is False
            )
            assert (
                await db.scalar(
                    text(
                        "SELECT status FROM profile.token_reservations WHERE harness_task_id=:job"
                    ),
                    {"job": job},
                )
                == "committed"
            )
            commands = (
                (
                    await db.execute(
                        text(
                            "SELECT command FROM profile.harness_operation "
                            "WHERE task_id=:job AND command IS NOT NULL"
                        ),
                        {"job": job},
                    )
                )
                .scalars()
                .all()
            )
            assert all(
                command["cleanup_confirmed"]
                and command["state"] in {"completed", "failed", "cancelled"}
                for command in commands
            )
        scope = RepositoryScope(
            row["thread_id"], row["user_id"], UUID(row["admission"]["project_id"])
        )
        await archive_sources(container, scope, job)
        await retire_test_runtime(container, scope)
    return {
        "paid_terminal_retired": True,
        "new_paid_calls": False,
        "journal_and_snapshots_preserved": True,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(UUID(sys.argv[-1])))))
    except BaseException as error:
        print(json.dumps({"stage": "paid_terminal_retire", "error": type(error).__name__}))
        sys.exit(1)
