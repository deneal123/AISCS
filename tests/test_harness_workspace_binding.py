"""Приватная среда задаётся backend, не моделью; resume не меняет её молча."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from service.services.chat.persistence.harness.admission.workspace_scope import bind_workspace
from service.shared.harness_protocol import Admission, HarnessFailure
from tests.test_harness_runtime_contract import admission


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "existing,supplied,changed",
    [(None, None, False), (None, "a" * 32, True), ("a" * 32, "a" * 32, False)],
)
async def test_same_or_legacy_binding_preserves_contract_limits_and_scope(
    existing, supplied, changed
):
    accepted = admission().model_copy(update={"workspace_id": existing})
    row = {"task_id": UUID(accepted.task_id), "admission": accepted.model_dump(mode="json")}
    owner = SimpleNamespace(project_id=accepted.project_id, generation=accepted.generation)
    db = SimpleNamespace(execute=AsyncMock())
    actual = await bind_workspace(db, row, owner, supplied)
    assert actual.model_dump(exclude={"workspace_id"}) == accepted.model_dump(
        exclude={"workspace_id"}
    )
    assert actual.workspace_id == (supplied or existing)
    assert db.execute.await_count == int(changed)
    if changed:
        assert json.loads(db.execute.await_args.args[1]["body"])["workspace_id"] == supplied


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["workspace", "project", "generation", "pdf"])
async def test_binding_conflict_is_not_a_new_generation_or_permission(monkeypatch, conflict):
    accepted = admission().model_copy(update={"workspace_id": "a" * 32})
    raw = accepted.model_dump(mode="json")
    if conflict == "pdf":
        raw["surface"] = "pdf"
    row = {"task_id": UUID(accepted.task_id), "admission": raw}
    owner = SimpleNamespace(
        project_id="other" if conflict == "project" else accepted.project_id,
        generation="other" if conflict == "generation" else accepted.generation,
    )
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="binding_changed"):
        await bind_workspace(db, row, owner, "b" * 32 if conflict == "workspace" else "a" * 32)
    db.execute.assert_not_awaited()


def test_optional_private_binding_is_legacy_readable_not_repr_or_proposal_authority():
    from service.shared.harness_protocol import ContractProposal

    accepted = admission()
    legacy = accepted.model_dump(mode="json", exclude={"workspace_id"})
    assert Admission.model_validate(legacy).workspace_id is None
    private = Admission.model_validate({**legacy, "workspace_id": "private-workspace-identity"})
    assert "private-workspace-identity" not in repr(private)
    with pytest.raises(ValueError):
        ContractProposal.model_validate(
            {
                "kind": "analysis",
                "workspace_id": str(uuid4()),
                "criteria": [{"criterion_id": "source", "kind": "read"}],
            }
        )
