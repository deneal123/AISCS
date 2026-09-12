from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from application.documents.projects import DocumentProjectError
from application.documents.sources import DocumentSourceService
from application.history import SAFE_SNAPSHOT_TYPES


def _item():
    return SimpleNamespace(policy=SimpleNamespace(root="/workspace"))


def test_document_authoring_snapshot_has_a_fixed_safe_commit_type() -> None:
    assert "document_authoring" in SAFE_SNAPSHOT_TYPES


@pytest.mark.asyncio
async def test_source_bundle_is_one_atomic_publish_and_one_snapshot() -> None:
    calls: list[tuple[str, bytes | None]] = []
    snapshots: list[str] = []

    async def run(_item, command, *, stdin_payload=None):
        calls.append((command, stdin_payload))
        return SimpleNamespace(stdout="__OK__")

    async def snapshot(_item, kind):
        snapshots.append(kind)
        return {"committed": True, "revision": "rev-2"}

    async def revision(_item):
        raise AssertionError("revision must come from the atomic snapshot response")

    projects = SimpleNamespace(manifest=lambda *_args: _value(({}, object())))
    service = DocumentSourceService(run, snapshot, revision, projects)
    digest = hashlib.sha256(b"draft").hexdigest()
    result = await service.publish(
        _item(),
        path="documents/paper",
        files={
            "main.tex": "\\documentclass{article}\\begin{document}ok\\end{document}",
            "content/body.tex": "body",
        },
        authoring_version=3,
        draft_digest=digest,
    )

    assert result["outcome"] == "published"
    assert result["revision"] == "rev-2"
    assert snapshots == ["document_authoring"]
    assert len(calls) == 2
    command, payload = next(call for call in calls if call[1] is not None)
    assert payload is not None
    assert "mv /workspace/documents/paper" in command
    assert "authoring-backup" in command
    assert calls[-1][1] is None
    assert calls[-1][0].startswith("rm -rf ")


@pytest.mark.asyncio
async def test_source_bundle_rejects_path_escape_before_container_call() -> None:
    called = False

    async def run(*_args, **_kwargs):
        nonlocal called
        called = True

    service = DocumentSourceService(
        run,
        lambda *_args: _value("rev"),
        lambda *_args: _value("rev"),
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )
    with pytest.raises(DocumentProjectError, match="authoring_invalid"):
        await service.publish(
            _item(),
            path="documents/paper",
            files={"main.tex": "ok", "../escape.tex": "bad"},
            authoring_version=1,
            draft_digest="a" * 64,
        )
    assert called is False


@pytest.mark.asyncio
async def test_source_bundle_rolls_back_after_publish_transport_failure() -> None:
    commands: list[str] = []

    async def run(_item, command, *, stdin_payload=None):
        commands.append(command)
        if stdin_payload is not None:
            raise OSError("private marker")
        return SimpleNamespace(stdout="")

    service = DocumentSourceService(
        run,
        lambda *_args: _value("rev"),
        lambda *_args: _value("rev"),
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )
    with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
        await service.publish(
            _item(),
            path="documents/paper",
            files={"main.tex": "safe"},
            authoring_version=1,
            draft_digest="b" * 64,
        )
    assert len(commands) == 2
    assert "authoring-backup" in commands[1]
    assert "private marker" not in str(commands)


@pytest.mark.asyncio
async def test_source_bundle_rolls_back_when_snapshot_is_not_committed() -> None:
    commands: list[tuple[str, bytes | None]] = []

    async def run(_item, command, *, stdin_payload=None):
        commands.append((command, stdin_payload))
        return SimpleNamespace(stdout="__OK__")

    async def snapshot(_item, _kind):
        return {"committed": False, "reason": "failed"}

    service = DocumentSourceService(
        run,
        snapshot,
        lambda *_args: _value("rev-should-not-be-read"),
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )

    with pytest.raises(DocumentProjectError, match="authoring_publish_failed"):
        await service.publish(
            _item(),
            path="documents/paper",
            files={"main.tex": "safe"},
            authoring_version=1,
            draft_digest="c" * 64,
        )

    assert len(commands) == 2
    rollback, payload = commands[-1]
    assert payload is None
    assert "rm -rf /workspace/documents/paper" in rollback
    assert "mv /workspace/.gpthub-document/authoring-backup-" in rollback


@pytest.mark.asyncio
async def test_source_bundle_accepts_no_changes_and_returns_current_revision() -> None:
    calls: list[tuple[str, bytes | None]] = []

    async def run(_item, command, *, stdin_payload=None):
        calls.append((command, stdin_payload))
        return SimpleNamespace(stdout="__OK__")

    async def snapshot(_item, _kind):
        return {"committed": False, "reason": "no_changes", "revision": "rev-stable"}

    service = DocumentSourceService(
        run,
        snapshot,
        lambda *_args: _value("rev-should-not-be-read"),
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )

    result = await service.publish(
        _item(),
        path="documents/paper",
        files={"main.tex": "safe"},
        authoring_version=1,
        draft_digest="d" * 64,
    )

    assert result["revision"] == "rev-stable"
    assert result["revision_changed"] is False
    assert calls[-1][1] is None
    assert calls[-1][0].startswith("rm -rf ")


async def _value(value):
    return value
