"""Изолированная сервисная приёмка PDF review/apply/build, не автоматическое исполнение."""

import asyncio
import json
import logging
import os
import sys
import traceback

from scripts.harness.live.documents.build import apply_and_build
from scripts.harness.live.documents.fixture import create
from scripts.harness.live.documents.review import propose
from scripts.harness.live.environment import backend_http, environment

STAGE = "environment"


async def main():
    global STAGE
    from service.services.chat.application.harness_capability import settings

    logging.disable(logging.CRITICAL)
    os.environ["HARNESS__PDF_ENABLED"] = "true"
    settings.cache_clear()
    async with environment() as container, backend_http(container):
        STAGE = "prepare_pdf_fixture"
        scope, ref, client, prefix = await create(container)
        try:
            STAGE = "propose_structural_review"
            proposal_id, before, project, owner, reference = await propose(container, scope, ref)
            STAGE = "apply_and_compile"
            await apply_and_build(client, prefix, ref, scope, proposal_id, before, project)
            STAGE = "reject_stale_document_resume"
            from scripts.harness.live.documents.continuation import resume_scope

            await resume_scope(container, owner, reference, changed=True)
            from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
            from service.shared.harness_protocol import Exchange

            task = await HarnessRuntimeRepository(container.infra.pg_connector).exchange(
                owner,
                Exchange(opcode="result"),
            )
            assert task["result"]["status"] != "completed"
            if os.environ.get("HARNESS_ACCEPTANCE_WORKSPACE_FAULT") == "document_acks":
                from scripts.harness.live.documents.build import assert_ack_boundaries

                await assert_ack_boundaries()
        finally:
            await client.aclose()
    print(
        json.dumps(
            {
                "structural_review_verified": True,
                "actual_pdf_verified": True,
                "build_replay_unchanged": True,
                "resume_scope_verified": True,
                "automatic_apply": False,
                "worker_covered": False,
                "fixture_data_removed": True,
            }
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(
            json.dumps(
                {
                    "stage": STAGE,
                    "error": type(error).__name__,
                    "frames": [
                        {"function": frame.name, "line": frame.lineno}
                        for frame in traceback.extract_tb(error.__traceback__)[-5:]
                    ],
                }
            )
        )
        sys.exit(1)
