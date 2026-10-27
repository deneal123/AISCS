import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.agents_client.agent_file_bridge import persist_generated_artifacts
from service.infrastructure.agents_client.required_artifacts import (
    delivery_reply,
    project_delivery,
    verified_content,
)
from service.services.chat.infrastructure.chat_worker.results.artifacts import (
    _collectable_workspace_inventory,
)


def descriptor(content=b"notes"):
    return {
        "path": "video-notes/run/notes.md",
        "size": len(content),
        "required": True,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupted", [False, True])
async def test_digest_bound_optional_file_uses_same_owner_intent_bridge_as_recovery(
    monkeypatch, corrupted
):
    import httpx

    from service.infrastructure import workspace_client

    original_client = httpx.AsyncClient
    payload = b"wrong" if corrupted else b"notes"
    monkeypatch.setattr(workspace_client, "_config", lambda: (True, "http://workspace", 1, "", 60))
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"content_b64": base64.b64encode(payload).decode()}
                )
            ),
            **kwargs,
        ),
    )
    offered = {**descriptor(), "required": False}
    files = await workspace_client.collect_artifacts(
        {"workspace_id": "fixture", "user_id": str(uuid4()), "token": "PRIVATE"}, [offered]
    )
    if corrupted:
        assert files == []
    else:
        assert len(files) == 1 and files[0]["required"] is True
        assert files[0]["sha256"] == offered["sha256"]
    assert offered["required"] is False


def test_only_verified_final_notes_enter_library_inventory():
    final = descriptor()
    assert _collectable_workspace_inventory(
        [
            {"path": "video-notes/run/transcript.md"},
            {"path": "video-notes/run/draft.md"},
            {"path": "documents/main.tex"},
            final,
        ]
    ) == [final]


@pytest.mark.parametrize("bad", ["wrong_hash", "wrong_size", "invalid_base64", "oversize"])
def test_transfer_is_hash_and_size_checked(bad):
    raw = b"notes"
    digest = hashlib.sha256(raw).hexdigest()
    encoded = base64.b64encode(raw).decode()
    assert verified_content(encoded, 5, digest, 100) == raw
    assert (
        verified_content(
            "??" if bad == "invalid_base64" else encoded,
            6 if bad == "wrong_size" else 5,
            "0" * 64 if bad == "wrong_hash" else digest,
            3 if bad == "oversize" else 100,
        )
        is None
    )


@pytest.mark.asyncio
async def test_required_artifact_is_owner_only_and_redelivery_has_stable_intent():
    owner = uuid4()
    service = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(file_id=uuid4(), file_url="opaque", file_key="private")
        )
    )
    art = {
        "filename": "notes.md",
        "file_b64": base64.b64encode(b"notes").decode(),
        "required": True,
    }
    for _ in range(2):
        _, metadata = await persist_generated_artifacts(
            file_service=service,
            user_id=owner,
            metadata={"_pending_artifacts": [art]},
            job_id="job",
        )
        assert metadata["generated_files"][0]["filename"] == "notes.md"
        assert "_pending_artifacts" not in metadata
    first, second = [call.kwargs for call in service.save.await_args_list]
    assert first == second and first["user_id"] == owner
    assert first["upload_intent_id"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, "anonymous", "00000000-0000-0000-0000-000000000000"])
async def test_required_save_rejects_non_owner_before_storage(owner):
    from service.infrastructure.agents_client.required_artifacts import save_required

    service = SimpleNamespace(save=AsyncMock())
    with pytest.raises(ValueError, match="^invalid_owner$"):
        await save_required(service, owner, "job", "notes.md", b"notes")
    service.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_delivery_does_not_change_owner_or_create_phantom_file():
    service = SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("SECRET-STORAGE-BODY")))
    _, metadata = await persist_generated_artifacts(
        file_service=service,
        user_id=uuid4(),
        job_id="job",
        metadata={
            "_pending_artifacts": [
                {
                    "filename": "notes.md",
                    "file_b64": "bm90ZXM=",
                    "required": True,
                }
            ]
        },
    )
    assert service.save.await_count == 1
    assert "generated_files" not in metadata and "_pending_artifacts" not in metadata
    result = {"workspace_artifacts": [descriptor()]}
    metadata = project_delivery(result["workspace_artifacts"], metadata)
    assert metadata["execution_status"] == "deferred"
    assert "не удалось" in delivery_reply("ready", metadata, result)
    assert "SECRET" not in str(metadata)


def test_download_is_promised_only_after_owned_file_persistence():
    result = {"workspace_artifacts": [descriptor()]}
    metadata = project_delivery(
        result["workspace_artifacts"],
        {
            "generated_files": [{"filename": "notes.md", "file_id": str(uuid4())}],
        },
    )
    assert "execution_status" not in metadata
    assert "скачать" in delivery_reply("working", metadata, result)
    assert delivery_reply("ordinary", {}, {}) == "ordinary"


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupted", [False, True])
async def test_collect_prioritizes_required_file_and_rejects_changed_content(
    monkeypatch, corrupted
):
    import httpx

    from service.infrastructure import workspace_client

    paths = []
    real_client = httpx.AsyncClient

    def handle(request):
        import json

        paths.append(json.loads(request.content)["path"])
        return httpx.Response(200, json={"content_b64": "YmFk" if corrupted else "bm90ZXM="})

    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 2, "", None)
    )
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw),
    )
    result = await workspace_client.collect_artifacts(
        {"workspace_id": "w", "user_id": "owner", "token": "private"},
        [{"path": f"other-{i}", "size": 5} for i in range(12)] + [descriptor()],
    )
    assert paths[0] == descriptor()["path"] and len(paths) == workspace_client.MAX_ARTIFACTS
    required = [item for item in result if item.get("required")]
    assert len(required) == (0 if corrupted else 1)


@pytest.mark.asyncio
async def test_worker_reports_deferred_after_persistence_seam_fails(monkeypatch):
    from service.infrastructure import workspace_client
    from service.services.chat.infrastructure.chat_worker.results import artifacts

    monkeypatch.setattr(
        workspace_client,
        "collect_artifacts",
        AsyncMock(
            return_value=[
                {
                    "filename": "notes.md",
                    "file_b64": "bm90ZXM=",
                    "required": True,
                }
            ]
        ),
    )
    monkeypatch.setattr(artifacts, "snapshot_workspace", AsyncMock())
    file_url, metadata = await artifacts.persist_all_artifacts(
        SimpleNamespace(save=AsyncMock(side_effect=RuntimeError("PRIVATE-FAILURE"))),
        uuid4(),
        {},
        "job",
        {"workspace_ref": {"workspace_id": "w"}},
        {"workspace_artifacts": [descriptor()]},
    )
    assert file_url is None and metadata["execution_status"] == "deferred"
    assert "generated_files" not in metadata and "_pending_artifacts" not in metadata


@pytest.mark.asyncio
async def test_verified_video_transcript_becomes_an_owned_library_download(monkeypatch):
    import httpx

    from service.infrastructure import workspace_client
    from service.services.chat.infrastructure.chat_worker.results import artifacts

    owner = uuid4()
    content = b"# Transcript\n[00:00] Chess lesson\n"
    item = {
        "path": "video-notes/run/opaque-source.md",
        "filename": "transcription.md",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "required": True,
    }
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 2, "", None)
    )
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={"content_b64": base64.b64encode(content).decode()},
                )
            ),
            **kw,
        ),
    )
    monkeypatch.setattr(artifacts, "snapshot_workspace", AsyncMock())
    file_id = uuid4()
    storage = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(
                file_id=file_id, file_url="opaque-download-url", file_key="private-key"
            )
        )
    )
    file_url, metadata = await artifacts.persist_all_artifacts(
        file_service=storage,
        user_id=owner,
        metadata={},
        job_id="video-job",
        engine_env={
            "workspace_ref": {
                "workspace_id": "workspace-1",
                "user_id": str(owner),
                "token": "private",
            }
        },
        execution_result={"workspace_artifacts": [item]},
    )

    assert file_url == "opaque-download-url"
    card = metadata["generated_files"][0]
    assert card["file_id"] == str(file_id)
    assert card["filename"] == "transcription.md"
    assert card["file_key"] == "private-key"
    assert "execution_status" not in metadata
    assert storage.save.await_args.kwargs["user_id"] == owner
    assert storage.save.await_args.kwargs["upload_intent_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("transcription.md", "transcription.md"),
        ("../transcription.md", "transcription.md"),
        (r"C:\private\transcription.md", "transcription.md"),
        ("bad\nname.md", "opaque-source.md"),
        ("x" * 256, "opaque-source.md"),
    ],
)
async def test_required_workspace_inventory_filename_survives_collection(
    monkeypatch, filename, expected
):
    import httpx

    from service.infrastructure import workspace_client

    raw = b"# transcript\n"
    source = {
        "path": "video-notes/run/opaque-source.md",
        "filename": filename,
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "required": True,
    }
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 1, "", None)
    )
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"content_b64": base64.b64encode(raw).decode()})
            ),
            **kw,
        ),
    )
    collected = await workspace_client.collect_artifacts(
        {"workspace_id": "w", "user_id": "owner", "token": "private"}, [source]
    )

    assert collected[0]["filename"] == expected
    assert collected[0]["required"] is True


@pytest.mark.asyncio
async def test_video_workspace_path_is_collected_as_required_library_file(monkeypatch):
    import httpx

    from service.infrastructure import workspace_client
    from service.services.chat.infrastructure.chat_worker.results import artifacts

    payload = b"verified transcript"
    digest = hashlib.sha256(payload).hexdigest()
    item = {
        "path": "video-notes/run/transcription.md",
        "filename": "transcription.md",
        "size": len(payload),
        "sha256": digest,
        "required": True,
    }
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 1, "", None)
    )
    monkeypatch.setattr(
        workspace_client.httpx,
        "AsyncClient",
        lambda **kw: real_client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"content_b64": base64.b64encode(payload).decode()}
                )
            ),
            **kw,
        ),
    )
    monkeypatch.setattr(artifacts, "snapshot_workspace", AsyncMock())
    file_id = uuid4()
    storage = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(file_id=file_id, file_url="opaque", file_key="private-key")
        )
    )
    file_url, metadata = await artifacts.persist_all_artifacts(
        file_service=storage,
        user_id=uuid4(),
        metadata={},
        job_id="video-job",
        engine_env={"workspace_ref": {"workspace_id": "w", "user_id": "owner", "token": "private"}},
        execution_result={"workspace_artifacts": [item]},
    )
    assert file_url == "opaque"
    assert metadata["generated_files"][0]["file_id"] == str(file_id)
    assert metadata["generated_files"][0]["filename"] == "transcription.md"
