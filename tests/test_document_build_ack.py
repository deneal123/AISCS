"""Потеря ACK запуска не даёт права запускать compiler второй раз."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.documents.build_ack import start_versioned_build
from service.infrastructure.workspace_client import WorkspaceConflict, WorkspaceUnavailable
from service.shared.document_review import operation_build_id


def fixture():
    ref = {"workspace_id": "workspace-1", "token": "PRIVATE"}
    payload = dict(
        path="documents/cats",
        operation_id=str(uuid4()),
        expected_revision="r1",
        final=False,
        coordination_fence=2,
    )
    receipt = dict(
        build_id=operation_build_id(ref["workspace_id"], payload["operation_id"]),
        source_revision="r1",
        final=False,
        state="building",
        source_digest="a" * 64,
    )
    return ref, payload, receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [None, {}, WorkspaceUnavailable("PRIVATE")])
async def test_unknown_ack_reads_same_build_once_without_second_start(missing):
    ref, payload, receipt = fixture()
    call = AsyncMock(side_effect=[missing, receipt])
    assert await start_versioned_build(call, ref, payload) == receipt
    assert [item.args[1] for item in call.await_args_list] == [
        "documents/builds",
        "documents/builds/" + receipt["build_id"],
    ]
    assert call.await_args.args[2] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [
        dict(build_id="other"),
        dict(final=True),
        dict(source_revision="r2"),
        dict(source_digest="bad"),
        dict(state="invented"),
    ],
)
async def test_unconfirmed_or_mismatched_status_remains_unknown(changed):
    ref, payload, receipt = fixture()
    call = AsyncMock(side_effect=[WorkspaceUnavailable("PRIVATE"), {**receipt, **changed}])
    with pytest.raises(WorkspaceUnavailable, match="outcome is unknown") as error:
        await start_versioned_build(call, ref, payload)
    assert "PRIVATE" not in str(error.value) and call.await_count == 2


@pytest.mark.asyncio
async def test_explicit_conflict_does_not_reconcile_another_recipe():
    ref, payload, _ = fixture()
    call = AsyncMock(side_effect=WorkspaceConflict("changed source"))
    with pytest.raises(WorkspaceConflict):
        await start_versioned_build(call, ref, payload)
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmed_ack_needs_no_status_read():
    ref, payload, receipt = fixture()
    call = AsyncMock(return_value=receipt)
    assert await start_versioned_build(call, ref, payload) == receipt
    call.assert_awaited_once()
