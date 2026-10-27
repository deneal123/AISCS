"""Opt-in authenticated confirmation lifecycle, without paid video processing."""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("VIDEO_CONFIRMATION_LIVE") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="requires isolated dev account and explicit GigaChat acceptance",
    ),
]


async def receive(socket):
    frame = json.loads(await socket.recv())
    return frame.get("data") or {} if frame.get("type") in {"claimed", "replay"} else frame


@pytest.mark.parametrize("decision", ["decline", "expiry"])
async def test_live_video_offer_is_explicit_owned_and_never_auto_accepts(decision):
    token = os.environ["E2E_AUTH_TOKEN"]
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=30
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S38 confirmation acceptance"})
        assert created.status_code == 201
        thread = created.json()["thread_id"]
        print(f"confirmation_thread={thread};scenario={decision}", flush=True)
        passive = await client.get(f"/api/chats/{thread}/work")
        assert passive.json()["workspace"]["state"] == "absent"
        async with (
            connect(
                f"ws://localhost:8001/api/chats/{thread}/ws",
                additional_headers={"Cookie": f"auth_token={token}"},
                max_size=2_000_000,
            ) as socket,
            asyncio.timeout(120),
        ):
            await socket.send(
                json.dumps(
                    {
                        "type": "message",
                        "id": str(uuid4()),
                        "text": "https://youtu.be/uTR9FdR3Ob0 Нужно сделать полный конспект видео",
                        "model": "GigaChat-2",
                        "memory_enabled": False,
                    },
                    ensure_ascii=False,
                )
            )
            offer = None
            while True:
                frame = await receive(socket)
                assert frame.get("type") != "error", "offer_run_failed"
                metadata = frame.get("metadata") or {}
                offered = metadata.get("mode_offer") or {}
                if offered.get("offer_id"):
                    offer = offered
                assert not metadata.get("generated_files"), "unconfirmed_file"
                assert not metadata.get("video_progress"), "unconfirmed_video_processing"
                if frame.get("type") == "agent_reply":
                    assert metadata.get("awaiting_confirmation"), "unconfirmed_answer"
                    break
            assert offer and offer.get("status") == "pending"
            snapshot = await client.get(f"/api/chats/{thread}/work")
            # An explicit chat request may allocate its sandbox preflight. The
            # expensive action, authoring and file creation must still be gated.
            if snapshot.json()["workspace"]["state"] != "absent":
                tree = await client.get(f"/api/chats/{thread}/workspace")
                assert not tree.json()["entries"], "unconfirmed_workspace_material"
            continuation = {
                "type": "message",
                "id": str(uuid4()),
                "text": "",
                "confirm_offer_id": offer["offer_id"],
                "confirmation_decision": "decline" if decision == "decline" else "accept",
            }
            if decision == "expiry":
                assert 0 < int(offer["expires_in_sec"]) <= 30
                await asyncio.sleep(int(offer["expires_in_sec"]) + 2)
                await socket.send(json.dumps(continuation))
                while True:
                    frame = await receive(socket)
                    assert frame.get("type") != "job_created", "expired_offer_started_job"
                    if frame.get("type") == "error":
                        assert "confirmation_expired" in json.dumps(frame), "wrong_expiry_code"
                        break
            else:
                await socket.send(json.dumps(continuation))
                continued_job = None
                while True:
                    frame = await receive(socket)
                    assert frame.get("type") != "error", "decline_failed"
                    if frame.get("type") == "job_created":
                        continued_job = frame["job_id"]
                        assert frame.get("confirmation_status") == "declined"
                    metadata = frame.get("metadata") or {}
                    assert not metadata.get("generated_files"), "declined_file"
                    assert not metadata.get("video_progress"), "declined_video_processing"
                    if frame.get("type") == "agent_reply" and frame.get("job_id") == continued_job:
                        break
                await socket.send(json.dumps({**continuation, "id": str(uuid4())}))
                while True:
                    frame = await receive(socket)
                    assert frame.get("type") != "error", "duplicate_decline_failed"
                    if frame.get("type") == "job_created":
                        assert frame["job_id"] == continued_job, "duplicate_continuation_job"
                        break
            history = await client.get(f"/api/chats/{thread}")
            assert history.status_code == 200
            messages = history.json()["messages"]
            assert len([row for row in messages if row.get("sender") == "user"]) == 1
            offers = [row.get("metadata", {}).get("mode_offer") for row in messages]
            offers = [row for row in offers if row and row.get("offer_id") == offer["offer_id"]]
            assert offers
            if decision == "decline":
                assert all(
                    row.get("status") == "declined" and not row.get("expired") for row in offers
                )
            else:
                assert all(row.get("expired") or row.get("status") == "expired" for row in offers)
            snapshot = await client.get(f"/api/chats/{thread}/work")
            if snapshot.json()["workspace"]["state"] != "absent":
                tree = await client.get(f"/api/chats/{thread}/workspace")
                assert not tree.json()["entries"], "declined_or_expired_workspace_material"
            print(f"confirmation_outcome={decision};user_messages=1;video_processing=0", flush=True)


async def test_live_cancel_between_authoring_parts_keeps_source_without_final_file():
    """Cooperative cancellation of an owned real run, never service fault injection."""
    token = os.environ["E2E_AUTH_TOKEN"]
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=30
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S38 cancellation acceptance"})
        assert created.status_code == 201
        thread = created.json()["thread_id"]
        print(f"cancellation_thread={thread}", flush=True)
        async with (
            connect(
                f"ws://localhost:8001/api/chats/{thread}/ws",
                additional_headers={"Cookie": f"auth_token={token}"},
                max_size=2_000_000,
            ) as socket,
            asyncio.timeout(180),
        ):
            await socket.send(
                json.dumps(
                    {
                        "type": "message",
                        "id": str(uuid4()),
                        "text": "https://youtu.be/aircAruvnKk Нужно сделать полный конспект видео",
                        "model": "GigaChat-2",
                        "memory_enabled": False,
                    },
                    ensure_ascii=False,
                )
            )
            task_id = None
            cancelled = False
            while True:
                frame = await receive(socket)
                if frame.get("type") == "job_created":
                    task_id = frame.get("celery_task_id") or task_id
                metadata = frame.get("metadata") or {}
                offer = metadata.get("mode_offer") or {}
                if offer.get("status") == "pending" and offer.get("offer_id"):
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
                progress = metadata.get("video_progress") or {}
                if (
                    not cancelled
                    and progress.get("stage") == "authoring"
                    and int(progress.get("current") or 0) >= 2
                ):
                    assert task_id and not cancelled, "missing_task_or_duplicate_cancel"
                    response = await client.post(f"/api/jobs/v1/task/{task_id}/cancel")
                    assert response.status_code == 200, "cancel_request_failed"
                    assert response.json().get("cancelled"), "cancel_not_acknowledged"
                    cancelled = True
                if frame.get("type") in {"agent_reply", "error"} and cancelled:
                    assert frame.get("type") == "agent_reply", "cancelled_settlement_not_finalized"
                    assert metadata.get("execution_status") == "partial", "cancelled_false_success"
                    assert not metadata.get("generated_files"), "cancelled_phantom_file"
                    break
            tree = await client.get(f"/api/chats/{thread}/workspace")
            assert tree.status_code == 200
            paths = [row["path"] for row in tree.json()["entries"]]
            assert any(path.endswith("/transcript.md") for path in paths), "source_lost"
            draft = next((path for path in paths if path.endswith("/authoring.json")), None)
            assert draft, "accepted_checkpoint_lost"
            saved = await client.post(f"/api/chats/{thread}/workspace/file", json={"path": draft})
            assert saved.status_code == 200
            checkpoint = json.loads(saved.json()["content"])
            assert checkpoint["body"]["accepted_parts"], "accepted_sections_lost"
            print("cancellation_outcome=cancelled;checkpoint_preserved=true", flush=True)
