"""Типизированная ошибка переживает contextmanager без подмены на TypeError."""

from contextlib import asynccontextmanager, contextmanager

import pytest

from service.domain.integration_failure import IntegrationFailure, IntegrationFailureCode
from service.domain.tools.workspace.client import WorkspaceUnavailable


@contextmanager
def boundary():
    yield


@asynccontextmanager
async def async_boundary():
    yield


def test_workspace_failure_keeps_identity_and_closed_code_through_contextmanager():
    error = WorkspaceUnavailable(IntegrationFailureCode.CONFLICT, retryable=True)
    with pytest.raises(IntegrationFailure) as raised, boundary():
        raise error
    assert raised.value is error and error.reason_code == "conflict"
    assert error.bounded_metadata()["retryable"] is True


@pytest.mark.asyncio
async def test_workspace_failure_keeps_identity_through_async_contextmanager():
    error = WorkspaceUnavailable(IntegrationFailureCode.TRANSPORT)
    with pytest.raises(IntegrationFailure) as raised:
        async with async_boundary():
            raise error
    assert raised.value is error and error.__traceback__ is not None
