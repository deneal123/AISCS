"""Legacy artifact refresh failures preserve history, never log private locators."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.persistence.chat_persistence_service import ChatPersistenceService

MARKER = "PRIVATE_ARTIFACT_HISTORY_SENTINEL"
LOGGER = "service.services.chat.persistence.chat_persistence_service"


@pytest.fixture
def history_logs(caplog):
    """Capture directly: importing service.main disables parent propagation."""
    logger = logging.getLogger(LOGGER)
    logger.addHandler(caplog.handler)
    previous = logger.level
    previous_propagation = logger.propagate
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        yield caplog
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(previous)
        logger.propagate = previous_propagation


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, TimeoutError])
async def test_failed_artifact_refresh_keeps_history_without_private_diagnostics(
    history_logs, failure
):
    signer = AsyncMock(side_effect=failure(f"https://storage.example/{MARKER}?credential={MARKER}"))
    service = ChatPersistenceService(None, SimpleNamespace(get_presigned_url_by_key=signer))
    item = {"file_key": MARKER, "file_url": "https://stale.example/owned", "filename": "file.pdf"}
    metadata = {"generated_files": [item], "usage": {"total": 17}}
    output = await service._refresh_artifact_links(metadata)
    assert output["generated_files"] == [item]
    assert output["file_url"] == item["file_url"]
    assert output["usage"] == metadata["usage"]
    signer.assert_awaited_once_with(file_key=MARKER)
    records = [record for record in history_logs.records if record.name == LOGGER]
    assert len(records) == 1
    assert MARKER not in history_logs.text
    assert records[0].exc_info is None and records[0].stack_info is None
    assert records[0].component == "artifact_history"
    assert records[0].failure_code == "unavailable"


@pytest.mark.asyncio
async def test_one_failed_link_does_not_block_other_artifacts_or_retry_the_call():
    signer = AsyncMock(side_effect=[RuntimeError(MARKER), "https://fresh.example/owned"])
    service = ChatPersistenceService(None, SimpleNamespace(get_presigned_url_by_key=signer))
    original = {
        "generated_files": [
            {"file_key": "one", "file_url": "https://old.example/one"},
            {"file_key": "two", "file_url": "https://old.example/two"},
        ]
    }
    output = await service._refresh_artifact_links(original)
    assert output["generated_files"][0]["file_url"] == "https://old.example/one"
    assert output["generated_files"][1]["file_url"] == "https://fresh.example/owned"
    assert original["generated_files"][1]["file_url"] == "https://old.example/two"
    assert signer.await_count == 2


@pytest.mark.asyncio
async def test_artifact_refresh_cancellation_stops_without_retry_or_failure_log(history_logs):
    signer = AsyncMock(side_effect=asyncio.CancelledError())
    service = ChatPersistenceService(None, SimpleNamespace(get_presigned_url_by_key=signer))
    with pytest.raises(asyncio.CancelledError):
        await service._refresh_artifact_links(
            {"generated_files": [{"file_key": "one"}, {"file_key": "two"}]}
        )
    assert signer.await_count == 1
    assert not [record for record in history_logs.records if record.name == LOGGER]
