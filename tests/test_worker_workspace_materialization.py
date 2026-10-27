"""Digest-bound workspace replay; no model call, workspace allocation or stale-token storage."""

import base64
import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure import workspace_client
from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.materialization.workspace import (
    recover_workspace_files,
    validated_inventory,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    PreparedCheckpointInvalid,
)


def inventory():
    return [
        {
            "path": "video-notes/run/notes.md",
            "size": 5,
            "sha256": hashlib.sha256(b"notes").hexdigest(),
            "required": True,
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expiry",
    [float("nan"), float("inf"), "NaN", "Infinity", "private-expiry-marker", {}, 10**1000],
    ids=["nan", "inf", "string_nan", "string_inf", "private_string", "object", "oversized_integer"],
)
async def test_invalid_binding_expiry_is_bounded_before_download(monkeypatch, expiry, caplog):
    owner = str(uuid4())
    request = SimpleNamespace(user_id=owner, thread_id="fixture-thread", job_id=str(uuid4()))
    monkeypatch.setattr(
        workspace_client,
        "read_binding_state",
        AsyncMock(
            return_value=(
                "ready",
                {
                    "workspace_id": "fixture-workspace",
                    "user_id": owner,
                    "expires_at": expiry,
                },
            )
        ),
    )
    collector = AsyncMock(return_value=[])
    monkeypatch.setattr(workspace_client, "collect_artifacts", collector)
    files = SimpleNamespace(save=AsyncMock())
    with pytest.raises(JobStateUnavailable) as error:
        await recover_workspace_files(
            request=request,
            facts={"workspace_id": "fixture-workspace", "workspace_files": inventory()},
            metadata={},
            file_service=files,
            redis_client=object(),
        )
    collector.assert_not_awaited()
    files.save.assert_not_awaited()
    assert "private-expiry-marker" not in str(error.value) + caplog.text


@pytest.mark.asyncio
async def test_transient_delivery_retries_only_owned_file_intent_without_model_work(
    monkeypatch, caplog
):
    """Controlled storage seam; no service stop or provider credential change."""
    owner, job, saved_id = uuid4(), str(uuid4()), uuid4()
    request = SimpleNamespace(user_id=str(owner), thread_id="delivery-fixture", job_id=job)
    binding = {
        "user_id": str(owner),
        "workspace_id": "fixture-workspace",
        "expires_at": time.time() + 300,
        "token": "PRIVATE_CAPABILITY_MARKER",
    }
    monkeypatch.setattr(
        workspace_client, "read_binding_state", AsyncMock(return_value=("ready", binding))
    )
    collector = AsyncMock(
        return_value=[
            {
                "filename": "notes.md",
                "file_b64": base64.b64encode(b"notes").decode(),
                "required": True,
                "sha256": inventory()[0]["sha256"],
            }
        ]
    )
    monkeypatch.setattr(workspace_client, "collect_artifacts", collector)
    saved = SimpleNamespace(file_id=saved_id, file_key="PRIVATE_KEY", file_url="owned-download")
    storage = SimpleNamespace(
        save=AsyncMock(side_effect=[RuntimeError("PRIVATE_ERROR"), saved, saved])
    )
    facts = {"workspace_id": "fixture-workspace", "workspace_files": inventory()}
    with pytest.raises(JobStateUnavailable):
        await recover_workspace_files(
            request=request, facts=facts, metadata={}, file_service=storage, redis_client=object()
        )
    for _ in range(2):
        result = await recover_workspace_files(
            request=request, facts=facts, metadata={}, file_service=storage, redis_client=object()
        )
        assert result["generated_files"][0]["file_id"] == str(saved_id)
    intents = [call.kwargs["upload_intent_id"] for call in storage.save.await_args_list]
    assert len(set(intents)) == 1
    assert all(call.kwargs["user_id"] == owner for call in storage.save.await_args_list)
    assert collector.await_count == 3  # Transfer only: authoring is outside this recovery seam.
    assert "PRIVATE_ERROR" not in str(result) + caplog.text
    assert "PRIVATE_CAPABILITY_MARKER" not in str(result) + caplog.text


@pytest.mark.parametrize("fault", ["escape", "absolute", "duplicate", "digest", "size", "optional"])
def test_inventory_rejects_unsafe_or_unbound_source(fault):
    raw = inventory()
    if fault == "escape":
        raw[0]["path"] = "../notes.md"
    elif fault == "absolute":
        raw[0]["path"] = "/notes.md"
    elif fault == "duplicate":
        raw.append({**raw[0], "path": "other/notes.md"})
    elif fault == "digest":
        raw[0]["sha256"] = "PRIVATE"
    elif fault == "size":
        raw[0]["size"] = True
    else:
        raw[0]["required"] = "false"
    with pytest.raises(PreparedCheckpointInvalid):
        validated_inventory(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "owner", "workspace", "expired", "redis", "changed", "missing"]
)
async def test_workspace_replay_validates_binding_content_and_reuses_job_intent(monkeypatch, fault):
    owner, job = uuid4(), str(uuid4())
    request = SimpleNamespace(user_id=str(owner), thread_id="fixture-thread", job_id=job)
    binding = {
        "user_id": str(owner),
        "workspace_id": "fixture-workspace",
        "expires_at": time.time() + 300,
        "token": "PRIVATE_TOKEN",
    }
    if fault == "owner":
        binding["user_id"] = str(uuid4())
    elif fault == "workspace":
        binding["workspace_id"] = "other"
    elif fault == "expired":
        binding["expires_at"] = time.time() - 1
    reader = AsyncMock(return_value=("unavailable" if fault == "redis" else "ready", binding))
    content = b"other" if fault == "changed" else b"notes"
    collector = AsyncMock(
        return_value=[]
        if fault == "missing"
        else [
            {
                "filename": "notes.md",
                "file_b64": base64.b64encode(content).decode(),
                "required": True,
                "sha256": inventory()[0]["sha256"],
            }
        ]
    )
    monkeypatch.setattr(workspace_client, "read_binding_state", reader)
    monkeypatch.setattr(workspace_client, "collect_artifacts", collector)
    saved_id = uuid4()
    files = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(
                file_id=saved_id, file_key="PRIVATE_KEY", file_url="PRIVATE_URL"
            )
        )
    )
    facts = {"workspace_id": "fixture-workspace", "workspace_files": inventory()}
    if fault is not None:
        with pytest.raises(JobStateUnavailable):
            await recover_workspace_files(
                request=request, facts=facts, metadata={}, file_service=files, redis_client=object()
            )
        files.save.assert_not_awaited()
    else:
        for _ in range(2):
            result = await recover_workspace_files(
                request=request, facts=facts, metadata={}, file_service=files, redis_client=object()
            )
            assert str(result["generated_files"][0]["file_id"]) == str(saved_id)
        calls = files.save.await_args_list
        assert calls[0].kwargs["upload_intent_id"] == calls[1].kwargs["upload_intent_id"]
        assert calls[0].kwargs["user_id"] == owner


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, False])
async def test_coordinator_recovers_notes_and_preserves_canonical_reply_receipts(
    monkeypatch, required
):
    import json

    from service.infrastructure.agents_client.required_artifacts import DELIVERY_READY_REPLY
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn
    from service.services.chat.infrastructure.chat_worker.results.prepared import (
        PreparedResultCoordinator,
    )
    from service.services.chat.infrastructure.chat_worker.run_contracts import (
        MutableRunState,
        WorkerRunRequest,
    )

    request = WorkerRunRequest(str(uuid4()), "fixture-thread", "fixture", str(uuid4()))
    accepted = accepted_turn(
        job_id=request.job_id,
        owner_id=request.user_id,
        thread_id=request.thread_id,
        reply="canonical answer",
        model="synthetic",
        usage={
            "total_tokens": 5,
            "per_call_usage": [
                {"call_id": "receipt", "model": "synthetic", "prompt": 3, "completion": 2}
            ],
        },
    )
    plan = {
        "version": 3,
        "reservation_id": None,
        "reserved_estimate": 0,
        "workspace_id": "fixture-workspace",
        "expires_at": time.time() + 300,
        "publications": [],
        "pricing": {"is_complex": False, "tools": []},
        "elapsed_seconds": 1,
        "library_files": [],
        "unresolved_assets": 0,
        "context": {
            "metadata": {"execution_status": "completed"},
            "observations": [],
            "executions": [],
        },
        "workspace_files": inventory(),
    }
    plan["workspace_files"][0]["required"] = required
    payload = {
        "thread_id": request.thread_id,
        "_accepted_turn_v1": accepted.payload(),
        "_materialization_plan_v1": plan,
    }

    async def stage(*args, **kwargs):
        payload["_prepared_turn_v1"] = json.loads(args[3])
        return True

    repo = SimpleNamespace(
        stage_prepared_turn=stage,
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": payload}
        ),
    )
    monkeypatch.setattr(
        workspace_client,
        "read_binding_state",
        AsyncMock(
            return_value=(
                "ready",
                {
                    "workspace_id": "fixture-workspace",
                    "user_id": request.user_id,
                    "expires_at": time.time() + 300,
                    "token": "PRIVATE_TOKEN",
                },
            )
        ),
    )
    monkeypatch.setattr(
        workspace_client,
        "collect_artifacts",
        AsyncMock(
            return_value=[
                {
                    "filename": "notes.md",
                    "file_b64": "bm90ZXM=",
                    "required": True,
                    "sha256": inventory()[0]["sha256"],
                }
            ]
        ),
    )
    file_id = uuid4()
    files = SimpleNamespace(
        save=AsyncMock(
            return_value=SimpleNamespace(
                file_id=file_id, file_key="PRIVATE_KEY", file_url="PRIVATE_URL"
            )
        ),
        fetch_file_metadata=AsyncMock(
            return_value=SimpleNamespace(file_id=file_id, file_key="PRIVATE_KEY")
        ),
        get_presigned_url_by_key=AsyncMock(return_value="PRIVATE_URL"),
    )
    state, session = MutableRunState(), AsyncMock()
    session.scalar.return_value = 0
    assert await PreparedResultCoordinator().restore(
        request=request,
        repository=repo,
        session=session,
        state=state,
        file_service=files,
        redis_client=object(),
    )
    stored = payload["_prepared_turn_v1"]["body"]
    assert stored["reply"] == "canonical answer"
    assert stored["usage"] == accepted.payload()["body"]["usage"]
    assert "PRIVATE" not in json.dumps(stored)
    assert state.restored_result["reply"] == (
        DELIVERY_READY_REPLY if required else "canonical answer"
    )
    assert str(state.restored_result["metadata"]["generated_files"][0]["file_id"]) == str(file_id)
