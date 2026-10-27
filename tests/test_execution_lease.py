"""Execution lease primitives: ownership, ambiguity, and safe pool cleanup."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_job_execution


class Session:
    def __init__(self, acquire=True, release=True):
        self.acquire = acquire
        self.release = release
        self.calls = []
        self.invalidated = 0

    async def scalar(self, query, params):
        self.calls.append((str(query), params))
        value = self.acquire if len(self.calls) == 1 else self.release
        if isinstance(value, BaseException):
            raise value
        return value

    async def invalidate(self):
        self.invalidated += 1


class Connector:
    def __init__(self, session):
        self.session = session

    @asynccontextmanager
    async def get_session_context(self):
        yield self.session


@pytest.mark.asyncio
@pytest.mark.parametrize("acquired", [True, False])
async def test_lease_releases_only_its_own_lock(acquired):
    session = Session(acquire=acquired)
    async with claim_job_execution(Connector(session), str(uuid4())) as held:
        assert held is acquired
    assert len(session.calls) == (2 if acquired else 1)
    assert session.invalidated == 0
    if acquired:
        assert session.calls[0][1] == session.calls[1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("release", [False, RuntimeError("PRIVATE_BODY")])
async def test_uncertain_release_invalidates_physical_connection(release, caplog):
    session = Session(release=release)
    async with claim_job_execution(Connector(session), str(uuid4())) as held:
        assert held
    assert session.invalidated == 1
    assert "PRIVATE_BODY" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("acquire", [None, RuntimeError("PRIVATE_BODY")])
async def test_unknown_acquisition_is_fail_closed(acquire):
    session = Session(acquire=acquire)
    with pytest.raises(JobStateUnavailable, match="Execution ownership unavailable"):
        async with claim_job_execution(Connector(session), str(uuid4())):
            pytest.fail("unverified ownership")
    assert session.invalidated == 1


@pytest.mark.asyncio
async def test_cancellation_during_acquisition_invalidates_connection():
    session = Session(acquire=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        async with claim_job_execution(Connector(session), str(uuid4())):
            pytest.fail("cancelled acquisition")
    assert session.invalidated == 1


@pytest.mark.asyncio
async def test_body_failure_is_preserved_and_lock_released():
    session = Session()
    with pytest.raises(RuntimeError, match="body"):
        async with claim_job_execution(Connector(session), str(uuid4())):
            raise RuntimeError("body")
    assert len(session.calls) == 2
    assert session.invalidated == 0
