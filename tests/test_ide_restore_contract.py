"""Reject malformed private identities before admitting a native request."""

from dataclasses import replace
from uuid import uuid4

import pytest

from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.checkpoints.restore import RestoreRecord
from service.services.chat.domain.ide.runtime import RepositoryScope


def record():
    blob = CheckpointBlob(RepositoryScope(uuid4(), uuid4(), uuid4()), uuid4(), "a" * 64, 100)
    return RestoreRecord(uuid4(), blob, uuid4(), uuid4(), 2_000_000_000, "b" * 64, "pending")


@pytest.mark.parametrize(
    "changes",
    [
        {"restore_id": "untrusted"},
        {"allocation_id": "untrusted"},
        {"base_allocation_id": "untrusted"},
        {"expires_at": True},
        {"expires_at": 1.5},
        {"expires_at": 0},
        {"storage_namespace": "PRIVATE_URL"},
        {"state": "ready"},
        {"blob": "PRIVATE_KEY"},
    ],
)
def test_invalid_identity_is_a_closed_error_without_raw_details(changes):
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_invalid$"):
        replace(record(), **changes)


def test_restore_cannot_reuse_base_allocation_or_unbounded_capsule():
    value = record()
    with pytest.raises(IdeCheckpointError):
        replace(value, allocation_id=value.base_allocation_id)
    for size in (0, 2**31):
        with pytest.raises(IdeCheckpointError):
            replace(value, blob=replace(value.blob, size=size))


def test_pending_record_is_not_implicit_dispatch_permission_and_private_fields_are_not_repr():
    value = record()
    assert value.attempt().state == "unknown"
    assert value.attempt(dispatch=True).state == "dispatching"
    assert value.attempt().expires_at == value.expires_at
    for private in (
        str(value.allocation_id),
        str(value.base_allocation_id),
        value.storage_namespace,
        value.blob.sha256,
    ):
        assert private not in repr(value)


@pytest.mark.parametrize("state", ["published", "expired", "conflict"])
def test_terminal_restore_cannot_be_converted_back_into_a_dispatch(state):
    with pytest.raises(IdeCheckpointError, match="ide_checkpoint_runtime_not_ready"):
        replace(record(), state=state).attempt(dispatch=True)
