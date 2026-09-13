from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from application.documents.checkpoints import DocumentCheckpointService, _lookup_script
from application.documents.projects import DocumentProjectError


def _item():
    return SimpleNamespace(policy=SimpleNamespace(root="/workspace"))


def _checkpoint() -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "section_authoring",
        "outline": {
            "title": "Document",
            "sections": [
                {
                    "section_id": "intro_01_0123456789",
                    "title": "Intro",
                    "purpose": "Explain",
                    "block_kinds": ["paragraph"],
                    "source_ids": [],
                }
            ],
        },
        "blocks": [{"block_id": "paragraph_001_0123456789", "kind": "paragraph"}],
        "accepted_section_ids": ["intro_01_0123456789"],
        "repair_used": False,
    }


@pytest.mark.asyncio
async def test_checkpoint_is_atomic_hidden_and_does_not_change_revision() -> None:
    calls: list[tuple[str, bytes | None]] = []

    async def run(_item, command, *, stdin_payload=None):
        calls.append((command, stdin_payload))
        return SimpleNamespace(stdout="")

    projects = SimpleNamespace(manifest=lambda *_args: _value(({}, object())))
    result = await DocumentCheckpointService(run, projects).write(
        _item(),
        path="documents/article",
        checkpoint=_checkpoint(),
        revision="rev-7",
        request_digest="a" * 64,
        evidence_digest="b" * 64,
    )

    assert result == {
        "outcome": "checkpointed",
        "stage": "section_authoring",
        "accepted_block_count": 1,
        "revision": "rev-7",
        "revision_changed": False,
    }
    assert len(calls) == 1
    command, payload = calls[0]
    assert "/.gpthub-document/checkpoints/" in command
    assert ".tmp" in command and "mv " in command
    stored = json.loads(payload or b"{}")
    assert stored["project_path"] == "documents/article"
    assert stored["blocks"][0]["block_id"] == "paragraph_001_0123456789"


@pytest.mark.asyncio
async def test_invalid_checkpoint_is_rejected_before_workspace_write() -> None:
    called = False

    async def run(*_args, **_kwargs):
        nonlocal called
        called = True

    service = DocumentCheckpointService(
        run,
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )
    with pytest.raises(DocumentProjectError, match="authoring_invalid"):
        await service.write(
            _item(),
            path="documents/article",
            checkpoint={**_checkpoint(), "stage": "private-marker"},
            revision="rev-7",
            request_digest="a" * 64,
            evidence_digest="b" * 64,
        )
    assert called is False


@pytest.mark.asyncio
async def test_failed_checkpoint_write_removes_only_its_temporary_file() -> None:
    calls: list[str] = []

    async def run(_item, command, *, stdin_payload=None):
        calls.append(command)
        if stdin_payload is not None:
            raise OSError("private marker")
        return SimpleNamespace(stdout="")

    service = DocumentCheckpointService(
        run,
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )
    with pytest.raises(DocumentProjectError, match="authoring_checkpoint_failed"):
        await service.write(
            _item(),
            path="documents/article",
            checkpoint=_checkpoint(),
            revision="rev-7",
            request_digest="a" * 64,
            evidence_digest="b" * 64,
        )
    assert len(calls) == 2
    assert calls[1].startswith("rm -f ")
    assert "private marker" not in repr(calls)


@pytest.mark.asyncio
async def test_latest_checkpoint_returns_only_matching_resumable_state() -> None:
    stored = {
        "project_path": "documents/article",
        "request_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "updated_at": 7,
        **_checkpoint(),
        "private_field": "must-not-cross-boundary",
    }

    async def run(_item, _command, **_kwargs):
        return SimpleNamespace(stdout=json.dumps(stored))

    service = DocumentCheckpointService(
        run,
        SimpleNamespace(manifest=lambda *_args: _value(({}, object()))),
    )
    result = await service.latest(
        _item(),
        request_digest="a" * 64,
        evidence_digest="b" * 64,
    )

    assert result is not None
    assert result["path"] == "documents/article"
    assert result["checkpoint"]["stage"] == "section_authoring"
    assert "private_field" not in repr(result)


def test_checkpoint_lookup_script_is_valid_python() -> None:
    compile(_lookup_script("/workspace/.gpthub-document/checkpoints"), "<checkpoint>", "exec")


async def _value(value):
    return value
