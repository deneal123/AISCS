"""Выделение PDF приватно, неизменяемо и привязано к исходному заданию."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.persistence.harness.admission.document_scope import (
    KEY,
    canonical_scope,
    read_document_scope,
    require_document_criteria,
    save_document_scope,
)
from service.shared.harness_protocol import ContractProposal, HarnessFailure
from tests.test_harness_runtime_contract import admission


def fixture():
    user, thread = str(uuid4()), str(uuid4())
    owner = SimpleNamespace(task_id=str(uuid4()), user_id=user, thread_id=thread)
    project = document_project_id(user, thread, "documents/cats")
    accepted = admission().model_copy(
        update={
            "surface": "pdf",
            "project_id": project,
            "actions": ("read", "document"),
        }
    )
    scope = {
        "path": "documents/cats",
        "expected_revision": "r1",
        "authoring_version": 2,
        "draft_digest": "a" * 64,
        "block_ids": ["intro"],
        "content": "PRIVATE_SOURCE",
        "coordination_capability": "PRIVATE_CAPABILITY",
    }
    row = {
        "task_id": uuid4(),
        "admission": accepted.model_dump(mode="json"),
        "job_payload": {},
        "checkpoint": None,
    }
    return owner, accepted, scope, row


def test_scope_contains_only_original_versioned_selection_without_capability_or_content():
    owner, accepted, scope, _ = fixture()
    value = canonical_scope(accepted, owner, scope)
    assert value["selection"]["block_ids"] == ["intro"]
    assert set(value) == {"schema_version", "selection"}
    assert "PRIVATE" not in json.dumps(value)
    assert set(value["selection"]) == {
        "path",
        "expected_revision",
        "authoring_version",
        "draft_digest",
        "block_ids",
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"path": "documents/other"},
        {"expected_revision": "user-new-version"},
    ],
)
def test_scope_cannot_select_another_project_or_rebase_admission(changed):
    owner, accepted, scope, _ = fixture()
    with pytest.raises(HarnessFailure, match="binding_changed"):
        canonical_scope(accepted, owner, {**scope, **changed})


@pytest.mark.asyncio
async def test_first_scope_is_saved_before_any_paid_or_effect_dispatch():
    owner, _, scope, row = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=False), execute=AsyncMock())
    await save_document_scope(db, row, owner, scope)
    arguments = db.execute.await_args.args[1]
    assert arguments["key"] == [KEY] and "PRIVATE" not in arguments["scope"]


@pytest.mark.asyncio
@pytest.mark.parametrize("started", ["checkpoint", "operation"])
async def test_existing_task_cannot_gain_scope_after_execution_started(started):
    owner, _, scope, row = fixture()
    if started == "checkpoint":
        row["checkpoint"] = {"state": "existing"}
    db = SimpleNamespace(scalar=AsyncMock(return_value=started == "operation"), execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="task_permission_denied"):
        await save_document_scope(db, row, owner, scope)
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeat_scope_is_read_only_but_new_selection_is_rejected():
    owner, accepted, scope, row = fixture()
    row["job_payload"][KEY] = canonical_scope(accepted, owner, scope)
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock())
    await save_document_scope(db, row, owner, scope)
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await save_document_scope(db, row, owner, {**scope, "block_ids": []})
    db.execute.assert_not_awaited()
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_child_reads_root_scope_not_new_child_session_data():
    owner, accepted, scope, row = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=canonical_scope(accepted, owner, scope)))
    result = await read_document_scope(db, row, owner)
    assert result["block_ids"] == ["intro"]
    assert str(db.scalar.await_args.args[1]["task"]) == owner.task_id


@pytest.mark.asyncio
async def test_legacy_task_without_scope_does_not_gain_autonomous_write_permissions():
    owner, _, _, row = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    with pytest.raises(HarnessFailure, match="task_permission_denied"):
        await read_document_scope(db, row, owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["", "documents/cats", "documents/other"])
async def test_pdf_criteria_cannot_select_another_project(target):
    owner, accepted, scope, row = fixture()
    db = SimpleNamespace(scalar=AsyncMock(return_value=canonical_scope(accepted, owner, scope)))
    proposal = ContractProposal(
        kind="document", criteria=[dict(criterion_id="slides", kind="pdf", target=target)]
    )
    if target == "documents/other":
        with pytest.raises(HarnessFailure, match="task_contract_invalid"):
            await require_document_criteria(db, row, owner, proposal)
    else:
        await require_document_criteria(db, row, owner, proposal)
