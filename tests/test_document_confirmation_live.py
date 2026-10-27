"""Opt-in metered dev check of attachment/confirmation restoration through WS.

Requires an isolated account. Uses a deliberately bibliography-incomplete source:
the result should be a saved draft, not a paid research run or a final publication.
"""

from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

from service.services.chat.infrastructure.chat_worker.context.metadata import (
    _DOCUMENT_FAILURE_CODES,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_CONFIRMATION") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="requires explicit metered dev confirmation acceptance",
    ),
]


async def _receive(socket, counts):
    value = json.loads(await socket.recv())
    if value.get("type") in {"claimed", "replay"}:
        value = value.get("data", {})
    kind = value.get("type")
    safe_kind = (
        kind
        if kind
        in {
            "job_created",
            "agent_reply",
            "stream_chunk",
            "status_update",
            "error",
            "heartbeat",
            "agent_complete",
            "job_complete",
            "result",
        }
        else "other"
    )
    counts[safe_kind] = counts.get(safe_kind, 0) + 1
    return value


async def test_confirmation_replay_uses_original_attachment_without_duplicate_message():
    token = os.environ["E2E_AUTH_TOKEN"]
    model = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-2")
    frame_counts: dict[str, int] = {}
    # The real dev threshold is 5000 credits. A tiny file estimates below it
    # and correctly bypasses confirmation. Use a bounded long-source fixture,
    # not a runtime-settings override, to exercise the genuine offer path.
    paragraph = (
        "Document pipelines separate authoring, compilation and delivery. "
        "Revision checks protect concurrent edits; durable sources belong to the Library. "
        "Audit and delivery failures must preserve the editable draft. "
        "No bibliographic records are provided.\n\n"
    )
    material = ("# Synthetic review materials\n\n" + paragraph * 200).encode()
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": token}, timeout=60
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 confirmation acceptance"})
        assert created.status_code == 201, "thread_create_failed"
        thread_id = str(UUID(created.json()["thread_id"]))
        try:
            upload = await client.post(
                "/api/chats/upload",
                data={"thread_id": thread_id, "upload_intent_id": str(uuid4())},
                files={
                    "file": (
                        "s37-materials.md",
                        material,
                        "text/markdown",
                    )
                },
            )
            assert upload.status_code == 200, "attachment_upload_failed"
            file_id = str(UUID(upload.json()["file_id"]))
            async with (
                connect(
                    f"ws://localhost:8001/api/chats/{thread_id}/ws",
                    additional_headers={"Cookie": f"auth_token={token}"},
                    max_size=2_000_000,
                ) as socket,
                asyncio.timeout(240),
            ):
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "id": str(uuid4()),
                            "text": "Напиши по прикрепленным материалам статью в PDF",
                            "model": model,
                            "route_override": "pdf_gen",
                            "file_ids": [file_id],
                            "attachments": [{"file_id": file_id, "name": "s37-materials.md"}],
                            "memory_enabled": False,
                        },
                        ensure_ascii=False,
                    )
                )
                while True:
                    event = await _receive(socket, frame_counts)
                    offer = (event.get("metadata") or {}).get("mode_offer") or {}
                    if offer.get("offer_id"):
                        break
                    if event.get("type") == "agent_reply":
                        pytest.fail("confirmation_offer_missing_before_terminal")
                    assert event.get("type") != "error", "offer_run_failed"
                assert offer.get("status") == "pending", "offer_not_pending"
                assert int(offer.get("estimated_credits", 0)) <= 10_000, "dev_budget_exceeded"
                claim = {
                    "type": "message",
                    "id": str(uuid4()),
                    "text": "",
                    "confirm_offer_id": offer["offer_id"],
                }
                await socket.send(json.dumps(claim))
                await socket.send(json.dumps(claim))
                accepted_jobs: list[str] = []
                terminal = None
                while len(accepted_jobs) < 2 or terminal is None:
                    event = await _receive(socket, frame_counts)
                    if event.get("confirmation_status") == "accepted":
                        accepted_jobs.append(str(event.get("job_id")))
                    if (
                        event.get("type") == "agent_reply"
                        and accepted_jobs
                        and event.get("job_id") == accepted_jobs[0]
                    ):
                        terminal = event.get("metadata") or {}
                    assert event.get("type") != "error", "confirmed_run_failed"
                assert len(set(accepted_jobs)) == 1, "duplicate_confirmation_job"
                assert terminal.get("requested_authoring_model") == model
                assert terminal.get("actual_authoring_model") == model
                outcome = terminal.get("document_outcome")
                if outcome in {"draft_ready", "completed", "deferred", "failed"}:
                    print("confirmation terminal outcome: " + outcome)
                # Transport/consent acceptance is separate from PDF quality.
                # Failed technical audit is an honest terminal, provided that
                # the editable project survives and the code is bounded.
                assert outcome in {"draft_ready", "failed"}, "unexpected_document_terminal"
                if outcome == "failed":
                    assert terminal.get("document_project_saved") is True
                    assert terminal.get("document_failure_code") in _DOCUMENT_FAILURE_CODES
                    print("confirmation failure code: " + terminal["document_failure_code"])
            history = await client.get(f"/api/chats/{thread_id}")
            assert history.status_code == 200, "history_unavailable"
            messages = history.json()["messages"]
            user_messages = [row for row in messages if row.get("sender") == "user"]
            assert len(user_messages) == 1, "duplicate_user_message"
            stored_attachments = (user_messages[0].get("metadata") or {}).get("attachments") or []
            assert any(item.get("file_id") == file_id for item in stored_attachments)
            stored_offers = [
                (row.get("metadata") or {}).get("mode_offer")
                for row in messages
                if (row.get("metadata") or {}).get("mode_offer")
            ]
            assert len(stored_offers) == 1, "offer_card_missing_or_duplicated"
            assert stored_offers[0]["status"] == "accepted", "accepted_card_lost_after_reload"
            assert stored_offers[0].get("expired") is not True
            # Keep the original end-to-end quality acceptance strict. The earlier
            # assertions diagnose consent/history independently, not excuse a
            # failed draft or turn that failure into a passing PDF scenario.
            assert outcome == "draft_ready", "document_quality_acceptance_failed"
        finally:
            # On failure, report only closed protocol counts, never frame contents.
            print("confirmation protocol counts: " + json.dumps(frame_counts, sort_keys=True))
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
