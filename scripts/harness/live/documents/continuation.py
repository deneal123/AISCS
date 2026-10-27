"""Настоящая worker admission ветка сохраняет root scope; не полный Celery-прогон."""

from service.services.chat.infrastructure.chat_worker.harness.admission import attach_harness
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.services.jobs.persistence.job_repository import JobRepository
from service.settings import config
from service.shared.harness_protocol import Exchange, HarnessFailure


async def resume_scope(container, owner, reference, *, changed=False):
    connector = container.infra.pg_connector
    runtime = HarnessRuntimeRepository(connector)
    before = await runtime.exchange(owner, Exchange(opcode="state"))
    admitted = before["snapshot"]["admission"]
    state = MutableRunState(
        reservation_id=admitted["reservation_id"],
        reserved_estimate=admitted["credit_limit"],
        execution_attempt_id=owner.attempt_id,
        harness_task_id=owner.task_id,
        harness_epoch=owner.epoch,
        engine_env={"workspace_ref": reference},
    )
    request = WorkerRunRequest(
        job_id=owner.job_id,
        user_id=owner.user_id,
        thread_id=owner.thread_id,
        text=admitted["goal"],
        selected_model="GigaChat-3-Lightning",
    )
    try:
        await attach_harness(
            request,
            state,
            JobRepository(connector),
            config,
            redis_client=container.infra.redis_client,
        )
    except HarnessFailure as error:
        assert changed and error.code == "binding_changed"
    else:
        assert not changed
        restored = state.engine_env["workspace_ref"]["document_context"]
        assert restored["block_ids"] == ["intro"] and restored["authoring_version"] == 2
        assert restored["content"] == reference["document_context"]["content"]
    assert await runtime.exchange(owner, Exchange(opcode="state")) == before


async def preserve_scope_through_status_writer(container, owner):
    from uuid import UUID

    from service.services.chat.persistence.harness.admission.document_scope import (
        load_owned_document_scope,
    )

    connector = container.infra.pg_connector
    saved = await load_owned_document_scope(connector, owner)
    repository = JobRepository(connector)
    async with connector.get_session_context() as db:
        job = await repository.fetch_job_by_id(UUID(owner.job_id), UUID(owner.user_id), session=db)
        assert job is not None
        # Ветка обычного worker lifecycle с payload, прочитанным до admission.
        job.payload = {"thread_id": owner.thread_id}
        await repository.update_job_status(job, session=db)
        await db.commit()
    assert await load_owned_document_scope(connector, owner) == saved
