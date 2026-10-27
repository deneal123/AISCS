"""Неизменяемое выделение PDF хранится у корневого job, не в агентском checkpoint."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.domain.documents.context import DocumentContext, document_project_id
from service.services.jobs.persistence.transitions import DOCUMENT_SCOPE_KEY
from service.shared.harness_protocol import Admission, HarnessFailure

KEY = DOCUMENT_SCOPE_KEY


def canonical_scope(admission, owner, context):
    try:
        selection = DocumentContext.model_validate(
            {key: value for key, value in context.items() if key in DocumentContext.model_fields}
        )
    except (AttributeError, ValueError):
        raise HarnessFailure("task_contract_invalid") from None
    if (
        admission.surface != "pdf"
        or selection.expected_revision != admission.source_revision
        or document_project_id(owner.user_id, owner.thread_id, selection.path)
        != admission.project_id
    ):
        raise HarnessFailure("binding_changed")
    # Только исходное выделение: не transcript, capabilities, содержимое или секреты.
    return {"schema_version": 1, "selection": selection.model_dump(mode="json")}


async def save_document_scope(db, row, owner, context):
    admission = Admission.model_validate(row["admission"])
    value = canonical_scope(admission, owner, context)
    saved = row["job_payload"].get(KEY)
    if saved is not None:
        if saved != value:
            raise HarnessFailure("operation_conflict")
        return
    already_started = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_grant WHERE task_id=:task) OR "
            "EXISTS(SELECT 1 FROM profile.harness_operation WHERE task_id=:task)"
        ),
        {"task": row["task_id"]},
    )
    if row["checkpoint"] is not None or already_started:
        # Старому/уже исполняемому заданию нельзя задним числом расширить выделение.
        raise HarnessFailure("task_permission_denied")
    await db.execute(
        text(
            "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,CAST(:key AS text[]),"
            "CAST(:scope AS jsonb),true) WHERE id=:task"
        ),
        {"key": [KEY], "scope": json.dumps(value), "task": row["task_id"]},
    )


async def read_document_scope(db, row, owner, *, required=True):
    # Human-question child и новый attempt читают тот же root, не свою новую session_data.
    value = await db.scalar(
        text(
            "SELECT payload->CAST(:key AS text) FROM profile.user_launch "
            "WHERE id=:task AND user_id=:user "
            "AND payload->>'thread_id'=:thread"
        ),
        {
            "key": KEY,
            "task": UUID(owner.task_id),
            "user": UUID(owner.user_id),
            "thread": owner.thread_id,
        },
    )
    if value is None and not required:
        return None
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise HarnessFailure("task_permission_denied")
    admission = Admission.model_validate(row["admission"])
    if canonical_scope(admission, owner, value.get("selection")) != value:
        raise HarnessFailure("binding_changed")
    return value["selection"]


async def require_document_criteria(db, row, owner, proposal):
    scope = await read_document_scope(db, row, owner, required=False)
    if scope and any(
        criterion.kind == "pdf" and criterion.target not in {"", scope["path"]}
        for criterion in proposal.criteria
    ):
        raise HarnessFailure("task_contract_invalid")


async def load_owned_document_scope(connector, owner):
    from service.services.chat.persistence.harness.state import owned_row, require_active

    try:
        async with connector.get_session_context() as db:
            row = await owned_row(db, owner)
            require_active(row)
            scope = await read_document_scope(db, row, owner)
            await db.commit()
            return scope
    except HarnessFailure:
        raise
    except Exception:
        raise HarnessFailure("checkpoint_unavailable") from None
