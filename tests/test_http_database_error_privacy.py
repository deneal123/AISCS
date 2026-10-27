"""Common HTTP/database boundaries must not log request or exception material."""

import asyncio
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from service.infrastructure.database import postgresql
from service.shared.error_handling.error_mapper import map_exception_to_error_response
from service.shared.error_handling.exceptions import RateLimitedError
from service.shared.presentation.handlers import exceptions_handlers as http
from service.shared.repositories.decorators.session_processor import _dispatch
from service.shared.repositories.exceptions import (
    RepositoryError,
    RepositoryIntegrityError,
    RepositoryMultipleResultsError,
    RepositoryNotFoundError,
    RepositoryOperationalError,
)

MARKER = "PRIVATE_REQUEST_CREDENTIAL_EXCEPTION_MARKER"


def capture_logger(monkeypatch, caplog, logger):
    monkeypatch.setattr(logger, "handlers", [caplog.handler])
    monkeypatch.setattr(logger, "propagate", False)
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "level", logging.DEBUG)


def request():
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "path": "/fixture/" + MARKER,
            "query_string": ("credential=" + MARKER).encode(),
            "headers": [],
            "server": ("fixture", 80),
            "client": ("127.0.0.1", 1),
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "validation", "general", "repository", "rate"])
async def test_http_handlers_log_only_bounded_outcome(kind, monkeypatch, caplog):
    capture_logger(monkeypatch, caplog, http.logger)
    calls = {
        "http": (http.http_exception_handler, HTTPException(503, MARKER)),
        "validation": (
            http.validation_exception_handler,
            RequestValidationError(
                [
                    {
                        "loc": ("body", MARKER),
                        "type": "value_error",
                        "msg": MARKER,
                        "input": MARKER,
                    },
                ]
            ),
        ),
        "general": (http.general_exception_handler, RuntimeError(MARKER)),
        "repository": (http.repository_exception_handler, RepositoryOperationalError(MARKER)),
        "rate": (http.rate_limited_exception_handler, RateLimitedError(MARKER, retry_after=2)),
    }
    handler, error = calls[kind]
    response = await handler(request(), error)
    assert (
        response.status_code
        == {
            "http": 503,
            "validation": 422,
            "general": 500,
            "repository": 503,
            "rate": 429,
        }[kind]
    )
    assert MARKER not in caplog.text
    assert caplog.records and all(record.exc_info is None for record in caplog.records)
    assert all(record.component == "http_boundary" for record in caplog.records)
    if kind == "repository":
        assert MARKER.encode() not in response.body


@pytest.mark.asyncio
async def test_repository_error_traceback_does_not_chain_raw_sql_or_credentials():
    failure = OperationalError(MARKER, {"password": MARKER}, RuntimeError(MARKER))
    with pytest.raises(RepositoryError) as caught:
        await _dispatch(AsyncMock(side_effect=failure), (), {}, session=AsyncMock())
    rendered = "".join(traceback.format_exception(caught.value))
    assert MARKER not in rendered
    assert caught.value.__suppress_context__


@pytest.mark.parametrize(
    "kind,message",
    [
        (RepositoryError, "Internal repository error"),
        (RepositoryIntegrityError, "Uniqueness violation"),
        (RepositoryNotFoundError, "Record not found"),
        (RepositoryMultipleResultsError, "Multiple records found where one was expected"),
        (RepositoryOperationalError, "Database unavailable"),
    ],
)
def test_repository_response_uses_static_legacy_codes(kind, message):
    result = map_exception_to_error_response(kind(MARKER)).error
    assert result.message == message
    assert result.type == kind.__name__
    assert result.code == kind.__name__.lower()
    assert MARKER not in result.model_dump_json()


def test_unknown_repository_subclass_cannot_export_its_name_or_custom_code():
    unknown = type(MARKER, (RepositoryError,), {"code": MARKER})
    result = map_exception_to_error_response(unknown(MARKER)).error
    assert result.code == "repositoryerror"
    assert result.type == "RepositoryError"
    assert MARKER not in result.model_dump_json()


@pytest.mark.asyncio
async def test_asgi_repository_mapping_keeps_status_without_private_cause(monkeypatch, caplog):
    capture_logger(monkeypatch, caplog, http.logger)
    app = FastAPI()
    http.setup_exception_handlers(app)

    @app.get("/fixture/{private}")
    async def fail(private: str):
        await _dispatch(
            AsyncMock(side_effect=OperationalError(MARKER, {}, RuntimeError(MARKER))),
            (),
            {},
            session=AsyncMock(),
        )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get("/fixture/" + MARKER)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repositoryoperationalerror"
    boundary_logs = [record for record in caplog.records if record.name == http.logger.name]
    assert len(boundary_logs) == 1
    assert boundary_logs[0].failure_code == "repository"
    assert boundary_logs[0].exc_info is None
    assert MARKER not in response.text
    assert MARKER not in boundary_logs[0].getMessage()


def connector_fixture(error):
    session = SimpleNamespace(execute=AsyncMock(side_effect=error), commit=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = session
    context.__aexit__.return_value = False
    connector = postgresql.PgConnector.__new__(postgresql.PgConnector)
    connector._session_maker = Mock(return_value=context)
    connector._engine = SimpleNamespace(dispose=AsyncMock(side_effect=error))
    return connector


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["session", "verify", "close"])
async def test_database_failure_logs_no_raw_body(operation, caplog, monkeypatch):
    capture_logger(monkeypatch, caplog, postgresql.logger)
    error = OSError(MARKER)
    connector = connector_fixture(error)
    if operation == "session":
        stream = connector.get_session()
        await anext(stream)
        with pytest.raises(OSError) as caught:
            await stream.athrow(error)
        assert caught.value is error
    elif operation == "verify":
        with pytest.raises(OSError) as caught:
            await connector.verify_connection()
        assert caught.value is error
    else:
        await connector.close()  # Existing best-effort cleanup remains best-effort.
    assert MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    failures = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert len(failures) == 1
    assert failures[0].component == "database"
    assert failures[0].failure_code in {"unavailable", "internal", "cleanup"}


@pytest.mark.asyncio
async def test_pool_retirement_failure_is_bounded(monkeypatch, caplog):
    capture_logger(monkeypatch, caplog, postgresql.logger)
    old = SimpleNamespace(sync_engine=SimpleNamespace(dispose=Mock(side_effect=OSError(MARKER))))
    monkeypatch.setattr(postgresql.PgConnector, "_engine", old)
    monkeypatch.setattr(postgresql.PgConnector, "_bound_loop", object())
    monkeypatch.setattr(postgresql.PgConnector, "_session_maker", None)
    replacement = object()
    monkeypatch.setattr(postgresql, "create_async_engine", Mock(return_value=replacement))
    connector = postgresql.PgConnector.__new__(postgresql.PgConnector)
    connector._force_new = False
    connector.config = SimpleNamespace(
        dsn=MARKER,
        settings=SimpleNamespace(
            db_echo=False,
            db_pool_size=1,
            db_max_overflow=0,
            db_pool_timeout=1,
            db_pool_recycle=1,
            db_pool_pre_ping=True,
        ),
    )
    assert connector._get_engine() is replacement
    old.sync_engine.dispose.assert_called_once_with(close=False)
    assert MARKER not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["session", "verify", "close"])
async def test_database_cancellation_is_not_reclassified(operation, monkeypatch, caplog):
    capture_logger(monkeypatch, caplog, postgresql.logger)
    error = asyncio.CancelledError()
    connector = connector_fixture(error)
    with pytest.raises(asyncio.CancelledError):
        if operation == "session":
            stream = connector.get_session()
            await anext(stream)
            await stream.athrow(error)
        elif operation == "verify":
            await connector.verify_connection()
        else:
            await connector.close()
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]
