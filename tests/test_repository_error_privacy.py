"""Persistence failures keep SQL, credentials and exception bodies out of logs."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, MultipleResultsFound, NoResultFound, OperationalError

from service.shared.repositories.decorators.session_processor import _dispatch
from service.shared.repositories.decorators.session_processor import logger as repository_logger
from service.shared.repositories.exceptions import RepositoryError, RepositoryOperationalError


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["integrity", "missing", "multiple", "transport", "internal"])
async def test_repository_failures_log_only_bounded_codes(kind, caplog, monkeypatch):
    # Parent app loggers may also disable propagation. Attach capture directly
    # to this real boundary logger and restore both settings after the test.
    monkeypatch.setattr(
        repository_logger, "handlers", [*repository_logger.handlers, caplog.handler]
    )
    monkeypatch.setattr(repository_logger, "propagate", False)
    marker = "private-sql-credential-body-marker"
    failures = {
        "integrity": IntegrityError(marker, {"secret": marker}, RuntimeError(marker)),
        "missing": NoResultFound(marker),
        "multiple": MultipleResultsFound(marker),
        "transport": OperationalError(marker, {"secret": marker}, RuntimeError(marker)),
        "internal": RuntimeError(marker),
    }
    function = AsyncMock(side_effect=failures[kind])
    session = AsyncMock()
    with pytest.raises(RepositoryError):
        await _dispatch(function, (), {}, session=session)
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert marker not in caplog.text
    records = [r for r in caplog.records if r.name.endswith("session_processor")]
    assert len(records) == 1 and records[0].exc_info is None
    assert records[0].component == "repository"
    assert records[0].failure_code in {
        "integrity",
        "not_found",
        "multiple_results",
        "unavailable",
        "internal",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["operation", "commit"])
@pytest.mark.parametrize("kind", ["integrity", "missing", "multiple", "transport", "internal"])
async def test_failed_rollback_is_bounded_unavailable_not_original_failure(
    phase, kind, caplog, monkeypatch
):
    monkeypatch.setattr(
        repository_logger, "handlers", [*repository_logger.handlers, caplog.handler]
    )
    monkeypatch.setattr(repository_logger, "propagate", False)
    marker = "private-rollback-sql-credential-body"
    failures = {
        "integrity": IntegrityError(marker, {"secret": marker}, RuntimeError(marker)),
        "missing": NoResultFound(marker),
        "multiple": MultipleResultsFound(marker),
        "transport": OperationalError(marker, {"secret": marker}, RuntimeError(marker)),
        "internal": RuntimeError(marker),
    }
    function = AsyncMock(return_value="result")
    session = AsyncMock()
    (function if phase == "operation" else session.commit).side_effect = failures[kind]
    session.rollback.side_effect = RuntimeError(marker)
    with pytest.raises(RepositoryOperationalError, match="^Database unavailable$") as caught:
        await _dispatch(function, (), {}, session=session)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert marker not in str(caught.value) and marker not in caplog.text
    session.rollback.assert_awaited_once()
    function.assert_awaited_once()
    assert session.commit.await_count == (1 if phase == "commit" else 0)
    records = [r for r in caplog.records if r.name.endswith("session_processor")]
    assert len(records) == 1 and records[0].exc_info is None
    assert records[0].component == "repository" and records[0].failure_code == "unavailable"


@pytest.mark.asyncio
async def test_rollback_cancellation_propagates_without_retry_or_failure_claim(caplog):
    session = AsyncMock()
    session.rollback.side_effect = asyncio.CancelledError()
    function = AsyncMock(side_effect=RuntimeError("private-original-body"))
    with pytest.raises(asyncio.CancelledError):
        await _dispatch(function, (), {}, session=session)
    session.rollback.assert_awaited_once()
    function.assert_awaited_once()
    assert not [r for r in caplog.records if r.name.endswith("session_processor")]


@pytest.mark.asyncio
async def test_caller_owned_transaction_is_not_rolled_back_by_mapper():
    supplied = AsyncMock()
    supplied.rollback.side_effect = RuntimeError("private-unused-rollback")
    function = AsyncMock(side_effect=IntegrityError("private", {}, RuntimeError("private")))
    with pytest.raises(RepositoryError):
        await _dispatch(function, (), {"session": supplied}, session=None)
    supplied.rollback.assert_not_awaited()
    supplied.commit.assert_not_awaited()
