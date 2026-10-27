"""Приватная привязка старого задания к проверенной среде при продолжении."""

from uuid import uuid4

from sqlalchemy import text

from service.services.chat.persistence.harness.state import save_checkpoint, snapshot
from service.shared.harness_protocol import Admission, HarnessFailure


async def bind_workspace(db, row, owner, workspace_id):
    admission = Admission.model_validate(row["admission"])
    if admission.project_id != owner.project_id or admission.generation != owner.generation:
        raise HarnessFailure("binding_changed")
    if workspace_id is None:
        return admission
    if admission.surface != "ide" or (
        admission.workspace_id is not None and admission.workspace_id != workspace_id
    ):
        raise HarnessFailure("binding_changed")
    if admission.workspace_id is None:
        admission = Admission.model_validate(
            {**admission.model_dump(), "workspace_id": workspace_id}
        )
        await db.execute(
            text(
                "UPDATE profile.harness_task SET admission=CAST(:body AS jsonb) WHERE task_id=:task"
            ),
            {"body": admission.model_dump_json(), "task": row["task_id"]},
        )
        if ((row.get("checkpoint") or {}).get("state") or {}).get("evidence"):
            # До появления привязки UI мог менять файлы, не инвалидируя этот task.
            # Сохраняем историю receipts, но требуем проверить текущую версию заново.
            current = await snapshot(db, {**row, "admission": admission.model_dump(mode="json")})
            await save_checkpoint(
                db,
                row,
                state=current.state.advance(source_revision="external:" + str(uuid4())),
                continuation=current.continuation,
            )
    return admission
