"""Save the actual paid test sources before retiring only their temporary runtime."""

from uuid import uuid5


async def archive_sources(container, scope, job):
    from service.composition.ide_commands import build_agent_console
    from service.services.chat.application.ide.checkpoints.capture import capture_checkpoint
    from service.services.chat.domain.ide.runtime import generation_tag

    service = build_agent_console(container.infra, prepare=True)
    resolved = await service.console.runtime.resolve(scope)
    rows = await service.saved.checkpoints.repository.inventory(scope)
    result = await capture_checkpoint(
        service.saved.edits,
        service.saved.checkpoints,
        scope,
        checkpoint_id=uuid5(job, "paid-acceptance-source-archive"),
        base_checkpoint_id=rows[0]["current_checkpoint_id"] if rows else None,
        generation=generation_tag(resolved.attempt),
        session="harness-paid-source-archive",
        limits=service.saved.limits,
    )
    assert result.state == "published" and result.upload_settled
