"""Direct prepared capture must validate the existing first-result envelope."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    ACCEPTED_KEY,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
    store_prepared_turn,
)
from tests.test_accepted_usage_lock import fixture


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["digest", "version", "metadata", "shape", "reply", "model", None]
)
async def test_direct_prepared_validates_existing_accepted_envelope(fault, caplog):
    accepted, row = fixture()
    body = accepted.payload()["body"]
    envelope = deepcopy(accepted.payload())
    if fault == "digest":
        envelope["sha256"] = "0" * 64
    elif fault == "version":
        envelope["body"]["version"] = True
    elif fault == "metadata":
        envelope = PreparedTurnCheckpoint.create(
            **{key: value for key, value in body.items() if key not in {"version", "metadata"}},
            metadata={"public": {"execution_status": "completed"}},
        ).payload()
    elif fault == "shape":
        envelope["PRIVATE_MARKER"] = "private-envelope-marker"
    elif fault in {"reply", "model"}:
        values = {key: value for key, value in body.items() if key not in {"version", "metadata"}}
        values[fault] = "different-value"
        envelope = accepted_turn(**values).payload()
    row["payload"][ACCEPTED_KEY] = envelope
    prepared = PreparedTurnCheckpoint.create(
        **{key: value for key, value in body.items() if key not in {"version", "metadata"}},
        metadata={"public": {"execution_status": "completed"}},
    )
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(return_value=row),
        stage_prepared_turn=AsyncMock(return_value=True),
    )
    session = AsyncMock()
    if fault is None:
        assert await store_prepared_turn(repo, session, prepared)
        repo.stage_prepared_turn.assert_awaited_once()
    else:
        with pytest.raises(PreparedCheckpointInvalid) as caught:
            await store_prepared_turn(repo, session, prepared)
        repo.stage_prepared_turn.assert_not_awaited()
        assert "private-envelope-marker" not in str(caught.value) + caplog.text
    session.commit.assert_not_awaited()
    assert row["payload"][ACCEPTED_KEY] == envelope
