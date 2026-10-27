import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from service.infrastructure import workspace_client
from service.services.chat.application.documents import preparation as module
from service.services.chat.domain.documents.preparation import (
    PdfPreparation,
    PdfPreparationNotFound,
    PdfPreparationScope,
    PdfPreparationUnavailable,
)
from service.services.chat.domain.ide.runtime import RuntimeObservation, WorkspaceBinding

pytestmark = pytest.mark.asyncio


class Store:
    def __init__(self):
        self.value = None
        self.ensure_owner = AsyncMock(return_value=True)

    async def get_owned(self, scope):
        return self.value

    async def claim_scaffold(self, scope, *, allow_retry=False):
        if self.value.scaffold_state == "idle" or (
            allow_retry and self.value.scaffold_state == "rejected"
        ):
            self.value = replace(self.value, scaffold_state="dispatching")
            return True
        return False

    async def reject_scaffold(self, scope):
        if self.value.scaffold_state == "dispatching":
            self.value = replace(self.value, scaffold_state="rejected")

    async def observe_project(self, scope):
        self.value = replace(self.value, scaffold_state="observed")
        return True

    async def claim(self, scope, *, ttl_sec, workspace_id=None, expires_at=None):
        if self.value is not None:
            return self.value, False
        self.value = PdfPreparation(
            None if workspace_id else uuid4(),
            workspace_id,
            expires_at or int(time.time()) + ttl_sec,
        )
        return self.value, workspace_id is None


@pytest.fixture
def setup(monkeypatch):
    scope = PdfPreparationScope(uuid4(), uuid4())
    store = Store()
    expiry = int(time.time()) + 1800
    ref = {
        "workspace_id": "a" * 32,
        "token": "PRIVATE",
        "root": "/workspace",
        "expires_at": expiry,
        **{key: str(value) for key, value in scope.params().items()},
    }
    allocator = SimpleNamespace(
        allocation_ttl=AsyncMock(return_value=1800),
        observe=AsyncMock(
            return_value=RuntimeObservation(
                "ready", WorkspaceBinding(ref["workspace_id"], ref["token"], expiry)
            )
        ),
    )
    read = AsyncMock(return_value=("absent", None))
    publish = AsyncMock(return_value=ref)
    view = AsyncMock(return_value={"revision": "r1", "entries": [], "truncated": False})
    create = AsyncMock(return_value={"path": module.DEFAULT_PDF_PATH})
    lease = SimpleNamespace(
        acquire_lease=AsyncMock(return_value=SimpleNamespace(fence=7)),
        release_lease=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(workspace_client, "read_binding_state", read)
    monkeypatch.setattr(workspace_client, "view", view)
    monkeypatch.setattr(workspace_client, "create_document_project", create)
    monkeypatch.setattr(module, "publish_pdf_binding", publish)
    current_binding = AsyncMock(return_value=ref)
    monkeypatch.setattr(module, "current_pdf_binding", current_binding)
    monkeypatch.setattr(module, "mint_capability", lambda *args, **kwargs: "PRIVATE_CAPABILITY")
    monkeypatch.setattr(module, "verify_capability", lambda token: SimpleNamespace())
    monkeypatch.setattr(module, "WorkspaceCollaborationStore", lambda *args, **kwargs: lease)
    service = module.PdfPreparationService(store, allocator, MagicMock())
    return SimpleNamespace(**locals())


def project(path="documents/default"):
    return {
        "revision": "r2",
        "entries": [{"path": f"/workspace/{path}/document.toml", "type": "file"}],
    }


async def test_first_entry_claims_before_dispatch_and_replay_only_observes(setup):
    s = setup
    s.view.side_effect = [s.view.return_value, project(), project()]
    first = await s.service.prepare(s.scope)
    assert s.store.value is not None
    assert first["state"] == "ready" and first["project_path"] == module.DEFAULT_PDF_PATH
    assert s.allocator.observe.await_args.kwargs == {"create": True, "initialize_history": True}
    assert "PRIVATE" not in repr(first) and "allocation_id" not in repr(first)
    await s.service.prepare(s.scope)
    assert [call.kwargs["create"] for call in s.allocator.observe.await_args_list] == [True, False]
    assert [call.kwargs["initialize_history"] for call in s.allocator.observe.await_args_list] == [
        True,
        False,
    ]
    s.create.assert_awaited_once()
    assert s.create.await_args.kwargs["expected_revision"] == "r1"
    assert s.create.await_args.kwargs["fence"] == 7
    s.lease.release_lease.assert_awaited_once()


async def test_foreign_thread_stops_before_redis_allocation_or_files(setup):
    s = setup
    s.store.ensure_owner.return_value = False
    with pytest.raises(PdfPreparationNotFound):
        await s.service.prepare(s.scope)
    s.read.assert_not_awaited()
    s.allocator.observe.assert_not_awaited()
    s.create.assert_not_awaited()


async def test_coordination_outage_is_not_absence(setup):
    s = setup
    s.read.return_value = ("unavailable", None)
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope)
    assert s.store.value is None
    s.allocator.allocation_ttl.assert_not_awaited()


async def test_existing_workspace_and_project_are_adopted_without_allocating_or_scaffolding(setup):
    s = setup
    s.read.return_value = ("ready", s.ref)
    s.view.return_value = project("documents/original")
    result = await s.service.prepare(s.scope)
    assert result["project_path"] == "documents/original"
    assert s.store.value.workspace_id == s.ref["workspace_id"]
    s.allocator.observe.assert_not_awaited()
    s.allocator.allocation_ttl.assert_not_awaited()
    s.publish.assert_not_awaited()
    s.create.assert_not_awaited()


@pytest.mark.parametrize("state", ["unknown", "pending", "unavailable", "rejected"])
async def test_ambiguous_dispatch_cannot_rearm_on_reload(setup, state):
    s = setup
    s.allocator.observe.return_value = RuntimeObservation(state)
    assert await s.service.prepare(s.scope) == {"state": "unavailable"}
    original = s.store.value
    assert await s.service.prepare(s.scope) == {"state": "unavailable"}
    assert s.store.value is original
    assert [call.kwargs["create"] for call in s.allocator.observe.await_args_list] == [True, False]
    s.create.assert_not_awaited()


async def test_expired_or_missing_adopted_binding_is_not_replaced_with_empty_workspace(setup):
    s = setup
    s.store.value = PdfPreparation(None, s.ref["workspace_id"], int(time.time()) - 1)
    assert await s.service.prepare(s.scope) == {"state": "expired"}
    s.store.value = PdfPreparation(None, s.ref["workspace_id"], int(time.time()) + 120)
    assert await s.service.prepare(s.scope) == {"state": "unavailable"}
    s.allocator.observe.assert_not_awaited()
    s.allocator.allocation_ttl.assert_not_awaited()
    s.create.assert_not_awaited()


@pytest.mark.parametrize(
    "view",
    [
        {"entries": [], "revision": "r1", "truncated": True},
        {"entries": [None], "revision": "r1"},
        {"entries": [], "revision": ""},
        {"entries": [{"path": "document.toml", "type": "file"}], "revision": "r1"},
    ],
)
async def test_incomplete_or_invalid_discovery_cannot_authorize_scaffold(setup, view):
    s = setup
    s.view.return_value = view
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope)
    s.create.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [workspace_client.WorkspaceUnavailable, workspace_client.WorkspaceConflict]
)
async def test_lost_scaffold_ack_is_reconciled_by_read_not_repeated_write(setup, error):
    s = setup
    s.service.initialize = AsyncMock(return_value=True)
    s.create.side_effect = error("PRIVATE")
    s.view.side_effect = [s.view.return_value, project()]
    assert (await s.service.prepare(s.scope))["state"] == "ready"
    s.create.assert_awaited_once()
    s.lease.release_lease.assert_awaited_once()
    s.service.initialize.assert_not_awaited()


async def test_only_a_new_confirmed_scaffold_can_initialize_semantic_content(setup):
    s = setup
    s.service.initialize = AsyncMock(return_value=True)
    s.create.return_value = {
        "path": module.DEFAULT_PDF_PATH,
        "revision": "fresh",
        "revision_changed": True,
    }
    s.view.side_effect = [s.view.return_value, project(), project()]
    assert (await s.service.prepare(s.scope))["state"] == "ready"
    assert (await s.service.prepare(s.scope))["state"] == "ready"
    s.service.initialize.assert_awaited_once()
    assert s.service.initialize.await_args.args[1] == s.create.return_value
    assert s.service.initialize.await_args.args[2] == 7
    s.create.assert_awaited_once()


async def test_unconfirmed_scaffold_does_not_claim_ready(setup):
    s = setup
    s.create.return_value = None
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope)
    s.create.assert_awaited_once()
    s.lease.release_lease.assert_awaited_once()


async def test_lost_scaffold_ack_never_replays_write_even_after_explicit_retry(setup):
    s = setup
    s.create.side_effect = workspace_client.WorkspaceUnavailable("PRIVATE")
    for retry in [False, True]:
        with pytest.raises(PdfPreparationUnavailable):
            await s.service.prepare(s.scope, retry_scaffold=retry)
    s.create.assert_awaited_once()
    assert s.store.value.scaffold_state == "dispatching"
    s.view.return_value = project()
    assert (await s.service.prepare(s.scope))["state"] == "ready"
    assert s.store.value.scaffold_state == "observed"
    s.create.assert_awaited_once()


async def test_only_explicit_retry_rearms_a_confirmed_revision_rejection(setup):
    s = setup
    s.create.side_effect = workspace_client.WorkspaceConflict("PRIVATE")
    for _ in range(2):
        with pytest.raises(PdfPreparationUnavailable):
            await s.service.prepare(s.scope)
    assert s.store.value.scaffold_state == "rejected"
    s.create.assert_awaited_once()
    s.create.side_effect = None
    s.create.return_value = {"path": module.DEFAULT_PDF_PATH}
    s.view.side_effect = [s.view.return_value, project()]
    assert (await s.service.prepare(s.scope, retry_scaffold=True))["state"] == "ready"
    assert s.create.await_count == 2
    assert [call.kwargs["create"] for call in s.allocator.observe.await_args_list] == [
        True,
        False,
        False,
    ]


async def test_missing_previously_observed_project_is_not_recreated_as_empty(setup):
    s = setup
    s.view.return_value = project()
    assert (await s.service.prepare(s.scope))["state"] == "ready"
    s.view.return_value = {"entries": [], "revision": "r3", "truncated": False}
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope, retry_scaffold=True)
    assert s.store.value.scaffold_state == "observed"
    s.create.assert_not_awaited()


async def test_replaced_binding_cannot_scaffold_or_publish_stale_project_facts(setup):
    s = setup
    s.current_binding.side_effect = PdfPreparationUnavailable
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope)
    s.create.assert_not_awaited()
    s.current_binding.side_effect = [s.ref, PdfPreparationUnavailable]
    s.view.return_value = project()
    with pytest.raises(PdfPreparationUnavailable):
        await s.service.prepare(s.scope)
    s.create.assert_not_awaited()


async def test_parallel_first_entries_share_one_allocation_claim(setup):
    s = setup
    s.view.return_value = project()
    results = await asyncio.gather(*(s.service.prepare(s.scope) for _ in range(8)))
    assert all(result["state"] == "ready" for result in results)
    assert sum(call.kwargs["create"] for call in s.allocator.observe.await_args_list) == 1
    assert len({call.args[1].allocation_id for call in s.allocator.observe.await_args_list}) == 1
    s.create.assert_not_awaited()
