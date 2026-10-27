"""Opt-in metered dev path: confirmed video -> Workspace -> owned Library download."""

import asyncio
import hashlib
import json
import os
import re
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("VIDEO_SUMMARY_LIVE") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="requires authenticated dev account and explicit metered acceptance",
    ),
]


async def test_confirmed_video_notes_are_a_verified_downloadable_workspace_file():
    model = os.getenv("VIDEO_SUMMARY_MODEL", "GigaChat-2")
    token = os.environ["E2E_AUTH_TOKEN"]
    url = os.getenv("VIDEO_SUMMARY_URL", "https://youtu.be/uTR9FdR3Ob0?is=0UG8_SLF3WCVARON")
    task = os.getenv("VIDEO_SUMMARY_REQUEST", "Нужно сделать полный конспект видео")
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": token},
        timeout=60,
    ) as client:
        response = await client.post("/api/chats/", json={"title": "Video notes dev acceptance"})
        assert response.status_code == 201, "thread_create_failed"
        thread = str(UUID(response.json()["thread_id"]))
        print("video thread: " + thread, flush=True)
        completed = False
        try:
            initial = await client.get(f"/api/chats/{thread}/work")
            assert initial.status_code == 200 and initial.json()["workspace"]["state"] == "absent"
            counts = {}
            job_id = None
            async with (
                connect(
                    f"ws://localhost:8001/api/chats/{thread}/ws",
                    additional_headers={"Cookie": f"auth_token={token}"},
                    max_size=2_000_000,
                ) as socket,
                asyncio.timeout(600),
            ):
                # watch_video is the existing explicit consent sent by the UI action.
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "id": str(uuid4()),
                            "text": url + " " + task,
                            "model": model,
                            "watch_video": os.getenv("VIDEO_SUMMARY_EXPLICIT_CONSENT") == "1",
                            "memory_enabled": False,
                        },
                        ensure_ascii=False,
                    )
                )
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") in {"claimed", "replay"}:
                        event = event.get("data") or {}
                    kind = event.get("type")
                    if kind == "error":
                        # Never wait ten minutes after a terminal failure or print its body.
                        pytest.fail("video_terminal_error", pytrace=False)
                    if kind in {
                        "job_created",
                        "status_update",
                        "stream_chunk",
                        "agent_reply",
                        "error",
                    }:
                        counts[kind] = counts.get(kind, 0) + 1
                    metadata = event.get("metadata") or {}
                    progress = metadata.get("video_progress") or {}
                    if progress.get("stage") in {
                        "probe",
                        "proxy",
                        "download",
                        "transcript",
                        "source_ready",
                        "authoring",
                        "workspace_save",
                        "library_delivery",
                    }:
                        print("video stage: " + progress["stage"], flush=True)
                    offer = metadata.get("mode_offer") or {}
                    if offer.get("status") == "pending" and offer.get("offer_id"):
                        assert int(offer.get("estimated_credits") or 0) <= 5000, (
                            "dev_budget_exceeded"
                        )
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "message",
                                    "id": str(uuid4()),
                                    "text": "",
                                    "confirm_offer_id": offer["offer_id"],
                                }
                            )
                        )
                    if kind == "job_created":
                        job_id = event.get("job_id")
                    if kind == "agent_reply" and event.get("job_id") == job_id:
                        break
            print("video transport: " + json.dumps(counts, sort_keys=True))
            status = metadata.get("execution_status", "unknown")
            print(
                "video execution: "
                + (
                    status
                    if status in {"completed", "partial", "failed", "deferred"}
                    else "unknown"
                )
            )
            assert metadata.get("generated_files"), "video_library_delivery_missing"
            assert metadata.get("selected_model") == model, "authoring_model_changed"
            assert metadata.get("execution_status") == "completed", "video_outcome_not_complete"
            usage = metadata.get("usage") or {}
            assert usage.get("model") == model and usage.get("actual_model") in {None, model}
            assert int(usage.get("total") or 0) > 0, "video_usage_missing"
            print(
                "video usage: "
                + json.dumps(
                    {
                        "model": model,
                        "tokens": int(usage["total"]),
                        "credits": int(usage.get("credits") or 0),
                    }
                )
            )
            file = next(
                row for row in metadata["generated_files"] if row["filename"].endswith(".md")
            )
            file_id = str(UUID(file["file_id"]))
            download = await client.get(
                f"/api/service/files/v1/{file_id}/download", follow_redirects=True
            )
            assert download.status_code == 200, "library_download_failed"
            text = download.content.decode("utf-8")
            assert "Все части доступной расшифровки обработаны." in text
            assert "визуальные детали не проверялись" in text
            interval = os.getenv("VIDEO_SUMMARY_EXPECT_RANGE")
            if interval:
                assert f"Выбранный диапазон: {interval}." in text, "requested_scope_missing"
            else:
                assert len(text) > 3000, "notes_unexpectedly_short"
            work = await client.get(f"/api/chats/{thread}/work")
            assert work.status_code == 200 and work.json()["workspace"]["state"] in {
                "ready",
                "recovered",
            }
            tree = await client.get(f"/api/chats/{thread}/workspace")
            assert tree.status_code == 200, "workspace_tree_failed"
            path = next(
                row["path"]
                for row in tree.json()["entries"]
                if row["path"].endswith(file["filename"])
            )
            saved = await client.post(f"/api/chats/{thread}/workspace/file", json={"path": path})
            assert saved.status_code == 200, "workspace_read_failed"
            digest = hashlib.sha256(download.content).hexdigest()
            assert hashlib.sha256(saved.json()["content"].encode()).hexdigest() == digest, (
                "download_digest_mismatch"
            )
            transcript_path = path.rsplit("/", 1)[0] + "/transcript.md"
            full = await client.post(
                f"/api/chats/{thread}/workspace/file", json={"path": transcript_path}
            )
            assert full.status_code == 200, "full_transcript_missing"
            assert len(full.json()["content"]) > 12000, "transcript_clipped"
            tail_minute = os.getenv("VIDEO_SUMMARY_TAIL_MINUTE")
            if tail_minute:
                stamps = re.findall(r"\[(\d+):\d{2}\]", full.json()["content"])
                assert stamps and int(stamps[-1]) >= int(tail_minute), "transcript_tail_missing"
            else:
                assert "[11:22]" in full.json()["content"], "transcript_tail_missing"
            print(
                "video download: "
                + json.dumps(
                    {"bytes": len(download.content), "sha256": digest, "transcript_complete": True}
                )
            )
            completed = True
        finally:
            # A failed run may have durable accepted usage awaiting settlement.
            # Deleting its thread here would destroy the recovery context.
            if completed and os.getenv("VIDEO_SUMMARY_CLEANUP") == "1":
                removed = await client.delete(f"/api/chats/{thread}")
                assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
