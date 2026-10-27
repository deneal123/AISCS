"""Worker composition for an owned, reserved harness task (feature gated)."""

from service.services.billing.application.frozen_pricing import freeze_pricing
from service.services.billing.application.pricing_service import PricingService
from service.services.billing.persistence.pricing_repository import PricingRepository
from service.services.chat.application.harness_capability import HarnessOwner, issue, settings
from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import Admission, HarnessFailure
from service.shared.model_class import is_free_local_model


def profile(context):
    config = settings()
    if config.ide_enabled and isinstance((context or {}).get("ide_context"), dict):
        return "ide_harness"
    if config.pdf_enabled and isinstance((context or {}).get("document_context"), dict):
        return "pdf_harness"
    return None


async def attach_harness(request, state, repository, config, *, redis_client=None):
    reference = state.engine_env.get("workspace_ref") or {}
    surface = profile(reference)
    if surface is None and not state.harness_task_id:
        return
    connector = repository.connector
    if (
        not state.reservation_id
        or not state.execution_attempt_id
        or (
            state.reserved_estimate <= 0
            and not (state.reserved_estimate == 0 and is_free_local_model(request.selected_model))
        )
    ):
        raise HarnessFailure("budget_unavailable")
    ide = reference.get("ide_context")
    document = reference.get("document_context") or {}
    is_ide = isinstance(ide, dict)
    project = str(ide["repository_id"]) if is_ide else document.get("project_id")
    if not project:
        project = document_project_id(str(request.user_id), request.thread_id, document["path"])
    generation = str(ide["generation"] if is_ide else reference["workspace_id"])
    owner = HarnessOwner(
        task_id=state.harness_task_id or request.job_id,
        job_id=request.job_id,
        user_id=str(request.user_id),
        thread_id=request.thread_id,
        attempt_id=state.execution_attempt_id,
        epoch=state.harness_epoch,
        project_id=project,
        generation=generation,
    )
    if state.harness_task_id:
        from service.services.chat.persistence.harness.rebind import rebind_harness

        owner = await rebind_harness(
            connector,
            owner,
            reservation_id=state.reservation_id,
            parent_id=request.question_resume.source_job_id if request.question_resume else None,
            workspace_id=reference.get("workspace_id") if is_ide else None,
        )
        state.harness_epoch = owner.epoch
        if not is_ide:
            from service.services.chat.infrastructure.chat_worker.harness.documents import (
                resume_document_context,
            )

            document = await resume_document_context(connector, redis_client, owner, reference)
            reference = {**reference, "document_context": document}
        state.engine_env["workspace_ref"] = {
            **reference,
            "harness_ref": {"task_id": owner.task_id, "capability": issue(owner)},
        }
        return
    limits = settings()
    admission = Admission(
        task_id=request.job_id,
        project_id=project,
        generation=generation,
        workspace_id=reference.get("workspace_id") if is_ide else None,
        surface="ide" if is_ide else "pdf",
        goal=request.text,
        source_revision=generation if is_ide else document["expected_revision"],
        actions=["read", "write", "exec"] if is_ide else ["read", "document"],
        credit_limit=state.reserved_estimate,
        reservation_id=state.reservation_id,
        pricing_model=request.selected_model,
        prompt_limit=limits.prompt_limit,
        completion_limit=limits.completion_limit,
    )
    tariff = await freeze_pricing(PricingService(PricingRepository(connector), config.billing))
    await HarnessRuntimeRepository(connector).admit(
        owner, admission, tariff, **({"document_context": document} if not is_ide else {})
    )
    state.harness_task_id = owner.task_id
    state.engine_env["workspace_ref"] = {
        **reference,
        "harness_ref": {"task_id": owner.task_id, "capability": issue(owner)},
    }
