"""Explicit unavailable manual-model Chat acceptance; no provider call is expected."""

import asyncio
import json
import os
import subprocess
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("S37_LIVE_MANUAL_MODEL") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="explicit unavailable manual-model dev acceptance",
    ),
]


async def _billing_snapshot():
    probe = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.billing.persistence.billing_repository import BillingRepository
async def main():
 connector=PgConnector(Config().pg)
 async with connector.get_session_context() as db:
  owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
   {'email':'s37-e2e-391e5206659a3654@example.com'})
  assert owner
  events=await db.scalar(text("SELECT count(*) FROM profile.billing_events "
   "WHERE user_id=:user AND event_type='usage'"),{'user':owner})
 balance=await BillingRepository(connector).get_balance(user_id=str(owner))
 assert balance is not None
 print(json.dumps({'topup':balance['topup'],'used':int(balance['used'] or 0),'events':events}))
try:
 asyncio.run(main())
except Exception:
 print('{}'); raise SystemExit(1)
"""
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=probe.encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "billing_snapshot_failed"
    return json.loads(result.stdout)


@pytest.mark.parametrize("model", ["EmbeddingsGigaR", "gpthub-unavailable-manual-chat"])
async def test_unavailable_manual_pdf_model_is_not_substituted_or_charged(model):
    before = await _billing_snapshot()
    token = os.environ["E2E_AUTH_TOKEN"]
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": token},
        timeout=60,
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 manual refusal"})
        assert created.status_code == 201
        thread = str(UUID(created.json()["thread_id"]))
        counts = {}
        try:
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
                            "text": "Создай PDF с текстом тест",
                            "model": model,
                            "route_override": "pdf_gen",
                            "confirm_expensive_run": True,
                            "memory_enabled": False,
                        }
                    )
                )
                while True:
                    frame = json.loads(await socket.recv())
                    if frame.get("type") in {"claimed", "replay"}:
                        frame = frame.get("data") or {}
                    kind = frame.get("type")
                    safe_kind = (
                        kind
                        if kind
                        in {
                            "job_created",
                            "status_update",
                            "stream_chunk",
                            "stream_complete",
                            "agent_reply",
                            "error",
                            "heartbeat",
                            "job_complete",
                            "job_failed",
                        }
                        else "other"
                    )
                    counts[safe_kind] = counts.get(safe_kind, 0) + 1
                    if kind == "error":
                        print(
                            "manual refusal error shape: "
                            + json.dumps(
                                {
                                    "has_error_code": "error_code" in frame,
                                    "has_code": "code" in frame,
                                    "has_metadata": isinstance(frame.get("metadata"), dict),
                                    "status_code": frame.get("status_code")
                                    if frame.get("status_code")
                                    in {400, 401, 403, 409, 422, 429, 500, 502, 503, 504}
                                    else None,
                                },
                                sort_keys=True,
                            )
                        )
                        code = (
                            frame.get("error_code")
                            or frame.get("code")
                            or (frame.get("metadata") or {}).get("failure_code")
                        )
                        safe_code = (
                            code
                            if code
                            in {
                                "no_compatible_model",
                                "selected_model_unavailable",
                                "model_routing_failed",
                                "job_execution_failed",
                                "chat_service_error",
                                "internal",
                                "processing_error",
                                "insufficient_credits",
                                "agent_processing_error",
                                "protocol_error",
                            }
                            else "unknown"
                        )
                        pytest.fail("manual_refusal_unexpected_terminal:" + safe_code)
                    if frame.get("type") == "agent_reply":
                        metadata = frame.get("metadata") or {}
                        break
                assert metadata.get("document_outcome") == "failed"
                assert metadata.get("document_failure_code") == "selected_model_unavailable"
                assert metadata.get("requested_authoring_model") == model
                assert metadata.get("actual_authoring_model") is None
                assert not metadata.get("document_project_saved")
                assert not metadata.get("generated_files")
            history = await client.get(f"/api/chats/{thread}")
            assert history.status_code == 200
            rows = history.json()["messages"]
            assert len([row for row in rows if row.get("sender") == "user"]) == 1
            replies = [row for row in rows if row.get("sender") == "assistant"]
            assert len(replies) == 1
            stored = replies[0].get("metadata") or {}
            assert stored.get("document_failure_code") == "selected_model_unavailable"
            assert stored.get("requested_authoring_model") == model
            assert stored.get("actual_authoring_model") is None
            assert not stored.get("generated_files")
            # The worker's terminal persisted reply follows reservation settlement.
            assert await _billing_snapshot() == before, "refusal_changed_balance_or_usage_events"
        finally:
            print("manual refusal frame counts: " + json.dumps(counts, sort_keys=True))
            unchanged = await _billing_snapshot() == before
            print("manual refusal billing unchanged: " + str(unchanged))
            removed = await client.delete(f"/api/chats/{thread}")
            assert removed.status_code in {200, 204}, "fixture_cleanup_failed"
            assert unchanged, "refusal_changed_balance_or_usage_events"
