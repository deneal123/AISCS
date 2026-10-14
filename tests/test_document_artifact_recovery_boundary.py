"""Unconfirmed artifact verification is an outage, not evidence of corruption."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.build_store import BuildManifestStore
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from domain.documents import DocumentArtifact, DocumentBuild


def build_fixture():
    return DocumentBuild(
        "recovery-owned",
        "owned",
        "/workspace/paper",
        "generic_document",
        1,
        "revision",
        "d" * 64,
        "draft",
        False,
        state="ready",
        artifacts=(
            DocumentArtifact(
                "pdf-owned",
                "pdf",
                "document.pdf",
                "application/pdf",
                10,
                "a" * 64,
                "/workspace/paper/artifacts/document.pdf",
            ),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(exit_code=0, stdout="__OK__", timed_out=True),
        SimpleNamespace(exit_code=0, stdout="__OK__", truncated=True),
        SimpleNamespace(exit_code=None, stdout="__OK__"),
        SimpleNamespace(exit_code=False, stdout="__OK__"),
        SimpleNamespace(exit_code=0, stdout="PRIVATE-INCOMPLETE"),
        SimpleNamespace(exit_code=124, stdout="PRIVATE-TIMEOUT"),
    ],
)
async def test_unconfirmed_verification_is_retryable_without_corruption_classification(result):
    registry = SimpleNamespace(exec_raw=AsyncMock(return_value=result))
    with pytest.raises(RuntimeError, match="^artifact verification unavailable$"):
        await BuildManifestStore().verify_artifacts(registry, object(), build_fixture())
    registry.exec_raw.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_outage_does_not_register_ready_or_persist_terminal_failure():
    @asynccontextmanager
    async def operation(_item):
        yield

    build = build_fixture()
    store = BuildManifestStore()
    store.load = AsyncMock(return_value=(build,))
    store.save = AsyncMock()
    manager = DocumentBuildManager(object(), object(), AsyncMock(), store=store)
    registry = SimpleNamespace(
        operation=operation,
        exec_raw=AsyncMock(return_value=SimpleNamespace(exit_code=0, timed_out=True)),
    )
    with pytest.raises(DocumentProjectError) as error:
        await manager.recover(registry, SimpleNamespace(workspace_id="owned"))
    assert error.value.code == "runtime_unavailable"
    assert build.state == "ready"
    assert manager.get("owned", build.build_id) is None
    assert "owned" not in manager._recovered_workspaces
    store.save.assert_not_awaited()
    registry.exec_raw.return_value = SimpleNamespace(
        exit_code=0, stdout="__OK__\n", timed_out=False, truncated=False
    )
    await manager.recover(registry, SimpleNamespace(workspace_id="owned"))
    assert manager.get("owned", build.build_id) is build
    assert "owned" in manager._recovered_workspaces
    assert build.state == "ready"
    store.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code, expected", [(0, True), (1, False)])
async def test_only_confirmed_verification_sets_validity(exit_code, expected):
    registry = SimpleNamespace(
        exec_raw=AsyncMock(
            return_value=SimpleNamespace(
                exit_code=exit_code,
                stdout="__OK__\n" if exit_code == 0 else "",
                timed_out=False,
                truncated=False,
            )
        )
    )
    assert (
        await BuildManifestStore().verify_artifacts(registry, object(), build_fixture()) is expected
    )
