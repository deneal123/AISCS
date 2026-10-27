"""Attachment preparation failures expose bounded diagnostics, never locators."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure import agent_context, repository_references
from service.services.chat.infrastructure.chat_worker.factory import ChatWorkerDependencyFactory


@pytest.fixture(autouse=True)
def capture_component_records(caplog):
    # Earlier app startup tests configure a non-propagating component logger.
    # Observe that actual logger directly; do not change production propagation.
    loggers = [agent_context.logger, repository_references.logger]
    attached = [logger for logger in loggers if caplog.handler not in logger.handlers]
    for logger in attached:
        logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        for logger in attached:
            logger.removeHandler(caplog.handler)


def assert_private_records(caplog, *markers):
    assert caplog.records
    for record in caplog.records:
        assert record.exc_info is None
        assert record.component == "attachment_context"
        assert record.failure_code in {"unavailable", "missing", "partial"}
        assert not any(marker in str(record.__dict__) for marker in markers)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["head", "presign"])
async def test_storage_failure_diagnostics_do_not_expose_private_key_or_body(caplog, operation):
    key, marker = "private-storage-key", "private-provider-body"
    service = SimpleNamespace(
        get_file_head_by_key=AsyncMock(side_effect=RuntimeError(marker)),
        get_presigned_url_by_key=AsyncMock(side_effect=RuntimeError(marker)),
    )
    with caplog.at_level(logging.DEBUG, logger=agent_context.__name__):
        result = (
            await agent_context._file_is_tabular(service, key)
            if operation == "head"
            else await agent_context._presign(service, key)
        )
    assert result is (False if operation == "head" else None)
    assert_private_records(caplog, key, marker)


@pytest.mark.asyncio
async def test_database_failure_diagnostics_do_not_expose_dsn(monkeypatch, caplog):
    marker = "postgresql://private-user:private-password@private-host/db"
    connector = SimpleNamespace(
        get_session_context=lambda: AsyncMock(
            __aenter__=AsyncMock(side_effect=RuntimeError(marker))
        )
    )
    monkeypatch.setattr(ChatWorkerDependencyFactory, "create_pg_connector", lambda *_: connector)
    assert await agent_context._dialog_file_rows(str(uuid4()), [str(uuid4())]) == ([], None)
    assert_private_records(caplog, marker)


@pytest.mark.parametrize("found,code", [(0, "missing"), (1, "partial")])
def test_missing_files_report_counts_without_file_identifiers(caplog, found, code):
    identities = {"private-file-one", "private-file-two"}
    agent_context._report_missing_rows(identities, found)
    assert_private_records(caplog, *identities)
    assert caplog.records[0].failure_code == code
    assert caplog.records[0].requested_count == 2
    assert caplog.records[0].found_count == found


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["read", "recall", "persist", "forget", "detach"])
async def test_async_redis_commands_are_awaited_once(monkeypatch, operation):
    redis = SimpleNamespace(
        lrange=AsyncMock(return_value=[b"repo-one"]),
        get=AsyncMock(return_value='["file-one"]'),
        set=AsyncMock(return_value=True),
        delete=AsyncMock(return_value=1),
    )
    monkeypatch.setattr(agent_context, "recall_last_thread_image_url", AsyncMock(return_value=None))
    if operation == "read":
        assert await agent_context.read_thread_repo_graphs(redis, "thread") == ["repo-one"]
        redis.lrange.assert_awaited_once_with("chat:thread:repo_graphs", 0, -1)
    elif operation == "recall":
        assert await agent_context._recall_or_persist_thread_tabular(redis, "thread", []) == [
            "file-one"
        ]
        redis.get.assert_awaited_once_with("chat:thread:file_ids")
    elif operation == "persist":
        assert await agent_context._recall_or_persist_thread_tabular(
            redis, "thread", ["file-one"], has_new_file=True
        ) == ["file-one"]
        redis.set.assert_awaited_once_with("chat:thread:file_ids", '["file-one"]', ex=7200)
    elif operation == "forget":
        await agent_context._forget_thread_files(redis, "thread")
        redis.delete.assert_awaited_once_with("chat:thread:file_ids")
    else:
        assert await agent_context.collect_message_extras(
            redis, "thread", [], detach_files=True
        ) == (None, False, [])
        redis.delete.assert_awaited_once_with("chat:thread:repo_graphs")
        redis.lrange.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_client", [False, True])
@pytest.mark.parametrize("operation", ["read", "recall", "forget", "detach"])
async def test_redis_failure_remains_bounded_without_thread_or_exception(
    monkeypatch, caplog, operation, async_client
):
    marker, thread = "private-redis-body", "private-thread-id"
    caplog.set_level(logging.DEBUG, logger=repository_references.__name__)
    redis = SimpleNamespace(
        lrange=lambda *_: (_ for _ in ()).throw(RuntimeError(marker)),
        get=lambda *_: (_ for _ in ()).throw(RuntimeError(marker)),
        delete=lambda *_: (_ for _ in ()).throw(RuntimeError(marker)),
    )
    if async_client:
        for method in ("lrange", "get", "delete"):
            setattr(redis, method, AsyncMock(side_effect=RuntimeError(marker)))
    monkeypatch.setattr(agent_context, "recall_last_thread_image_url", AsyncMock(return_value=None))
    with caplog.at_level(logging.DEBUG, logger=agent_context.__name__):
        if operation == "read":
            assert await agent_context.read_thread_repo_graphs(redis, thread) == []
        elif operation == "recall":
            assert await agent_context._recall_or_persist_thread_tabular(redis, thread, []) == []
        elif operation == "forget":
            await agent_context._forget_thread_files(redis, thread)
        else:
            assert await agent_context.collect_message_extras(
                redis, thread, [], detach_files=True
            ) == (None, False, [])
    assert_private_records(caplog, marker, thread)


@pytest.mark.asyncio
async def test_successful_forget_does_not_log_thread_id(caplog):
    thread = "private-thread-id"
    redis = SimpleNamespace(delete=AsyncMock(return_value=1))
    await agent_context._forget_thread_files(redis, thread)
    assert_private_records(caplog, thread)


@pytest.mark.asyncio
async def test_async_redis_cancellation_does_not_retry_or_report_success(caplog):
    import asyncio

    entered = asyncio.Event()

    async def pending(*_):
        entered.set()
        await asyncio.Event().wait()

    redis = SimpleNamespace(delete=AsyncMock(side_effect=pending))
    operation = asyncio.create_task(agent_context._forget_thread_files(redis, "thread"))
    await asyncio.wait_for(entered.wait(), 1)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    redis.delete.assert_awaited_once_with("chat:thread:file_ids")
    assert not caplog.records
