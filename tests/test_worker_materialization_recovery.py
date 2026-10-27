"""Recovery plan conformance, not proof of early-latch worker integration."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
    MaterializationPlan,
    recover_materialization,
    stage_materialization,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    PreparedCheckpointInvalid,
)


def payload():
    return {
        "version": 1,
        "reservation_id": str(uuid4()),
        "reserved_estimate": 70,
        "workspace_id": None,
        "expires_at": None,
        "publications": [],
        "pricing": {"is_complex": False, "tools": []},
        "elapsed_seconds": 1.5,
        "library_files": [],
        "unresolved_assets": 0,
    }


def context_payload():
    raw = payload()
    raw["version"] = 2
    raw["context"] = {
        "metadata": {"execution_status": "completed"},
        "observations": [
            {
                "steps": ["deep_research", "pdf_gen"],
                "cost_class": "expensive",
                "request_text": "private catalog example",
            }
        ],
        "executions": [{"workflow_id": str(uuid4()), "version": 1, "status": "succeeded"}],
    }
    return raw


def test_builder_preserves_catalog_without_engine_credentials_or_lost_asset_success():
    import time

    from service.services.chat.infrastructure.chat_worker.materialization.builder import (
        build_materialization_plan,
    )

    state = SimpleNamespace(
        engine_env={
            "workspace_ref": {
                "workspace_id": "workspace-fixture",
                "expires_at": 2000000000,
                "capability": "PRIVATE_CAPABILITY",
                "token": "PRIVATE_TOKEN",
            }
        },
        reservation_id=None,
        reserved_estimate=0,
    )
    prepared = SimpleNamespace(workflow_observations=[], workflow_executions=[])
    plan = build_materialization_plan(
        metadata={"execution_status": "completed", "_pending_artifacts": [{"bytes": b"PRIVATE"}]},
        execution_result={"workspace_artifacts": [{"path": "notes.md", "required": True}]},
        state=state,
        prepared=prepared,
        started_at=time.monotonic(),
    )
    projected = plan.payload()
    assert projected["unresolved_assets"] == 2
    assert projected["workspace_id"] == "workspace-fixture"
    assert projected["context"]["metadata"] == {"execution_status": "completed"}
    assert "PRIVATE" not in repr(projected)


@pytest.mark.asyncio
async def test_context_preserves_metadata_and_catalog_as_separate_private_projections():
    raw = context_payload()
    plan = MaterializationPlan.from_payload(raw)
    result = await recover_materialization(plan, owner_id=str(uuid4()), file_service=object())
    assert result["metadata"]["execution_status"] == "completed"
    assert result["catalog"]["observations"] == raw["context"]["observations"]
    assert "private catalog example" not in repr(result["metadata"])
    result["catalog"]["observations"][0]["steps"].append("mutated")
    assert plan.payload() == raw


@pytest.mark.parametrize("fault", ["credential", "metadata", "file", "observation", "execution"])
def test_context_rejects_private_leaks_unknown_fields_and_invalid_catalog(fault):
    raw = context_payload()
    context = raw["context"]
    if fault == "credential":
        context["metadata"]["capability"] = "PRIVATE"
    elif fault == "metadata":
        context["metadata"]["request_text"] = "PRIVATE"
    elif fault == "file":
        context["metadata"]["generated_files"] = [{"file_id": str(uuid4())}]
    elif fault == "observation":
        context["observations"][0]["steps"] = ["private/path", "pdf_gen"]
    else:
        context["executions"][0]["version"] = True
    with pytest.raises(PreparedCheckpointInvalid):
        MaterializationPlan.from_payload(raw)


@pytest.mark.asyncio
async def test_atomic_admission_carries_accepted_receipts_and_plan_without_commit():
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    accepted = accepted_turn(
        job_id=str(uuid4()),
        owner_id=str(uuid4()),
        thread_id="fixture-thread",
        reply="accepted",
        model="synthetic",
        usage={"per_call_usage": []},
    )
    plan = MaterializationPlan.from_payload(payload())
    from service.models.key_value import ProcessingStatus

    repo = SimpleNamespace(
        stage_accepted_materialization=AsyncMock(return_value=True),
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {"thread_id": "fixture-thread"},
            }
        ),
    )
    session = AsyncMock()
    assert await stage_materialization(repo, session, accepted, plan)
    import json

    envelope = json.loads(repo.stage_accepted_materialization.await_args.args[3])
    assert set(envelope) == {"_accepted_turn_v1", "_materialization_plan_v1"}
    assert envelope["_accepted_turn_v1"] == accepted.payload()
    assert envelope["_materialization_plan_v1"] == plan.payload()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["replay", "plan", "terminal", "prepared", "missing"])
async def test_atomic_admission_replay_never_replaces_materialization(fault):
    from service.models.key_value import ProcessingStatus
    from service.services.chat.infrastructure.chat_worker.results.accepted import accepted_turn

    accepted = accepted_turn(
        job_id=str(uuid4()),
        owner_id=str(uuid4()),
        thread_id="fixture-thread",
        reply="accepted",
        model="synthetic",
        usage={"per_call_usage": []},
    )
    plan = MaterializationPlan.from_payload(payload())
    stored = {
        "thread_id": "fixture-thread",
        "_accepted_turn_v1": accepted.payload(),
        "_materialization_plan_v1": plan.payload(),
    }
    if fault == "plan":
        stored["_materialization_plan_v1"]["reserved_estimate"] += 1
    if fault == "prepared":
        stored["_prepared_turn_v1"] = {}
    row = {
        "payload": stored,
        "status": ProcessingStatus.SUCCESS if fault == "terminal" else ProcessingStatus.PROCESSING,
    }
    repo = SimpleNamespace(
        stage_accepted_materialization=AsyncMock(return_value=False),
        lock_prepared_turn=AsyncMock(return_value=None if fault == "missing" else row),
    )
    if fault == "replay":
        assert not await stage_materialization(repo, AsyncMock(), accepted, plan)
    else:
        with pytest.raises(PreparedCheckpointInvalid):
            await stage_materialization(repo, AsyncMock(), accepted, plan)


@pytest.mark.asyncio
async def test_invalid_plan_still_commits_bare_accepted_usage_without_private_payload():
    import json
    import time

    from service.services.chat.infrastructure.chat_worker.results.prepared import (
        PreparedResultCoordinator,
    )
    from service.services.chat.infrastructure.chat_worker.run_contracts import (
        MutableRunState,
        WorkerRunRequest,
    )

    request = WorkerRunRequest(str(uuid4()), "fixture-thread", "fixture", str(uuid4()))
    from service.models.key_value import ProcessingStatus

    repo = SimpleNamespace(
        stage_accepted_turn=AsyncMock(return_value=True),
        lock_prepared_turn=AsyncMock(
            return_value={
                "status": ProcessingStatus.PROCESSING,
                "payload": {"thread_id": "fixture-thread"},
            }
        ),
    )
    session = AsyncMock()
    with pytest.raises(JobStateUnavailable) as caught:
        await PreparedResultCoordinator().capture_accepted(
            request=request,
            repository=repo,
            session=session,
            state=MutableRunState(),
            execution_result={
                "resolved_model": "synthetic",
                "total_tokens": 5,
                "per_call_usage": [
                    {
                        "call_id": "receipt",
                        "model": "synthetic",
                        "prompt": 3,
                        "completion": 2,
                        "arguments": "PRIVATE_ARGUMENTS",
                    }
                ],
            },
            reply="accepted",
            metadata={},
            started_at=time.monotonic(),
            prepared=SimpleNamespace(
                workflow_observations=[{"PRIVATE": "bad context"}], workflow_executions=[]
            ),
        )
    saved = json.loads(repo.stage_accepted_turn.await_args.args[3])
    assert saved["body"]["reply"] == "accepted"
    assert saved["body"]["usage"]["total_tokens"] == 5
    assert saved["body"]["metadata"] == {}
    assert "PRIVATE" not in str(caught.value) + repr(saved)
    session.commit.assert_awaited_once()


def test_plan_does_not_share_mutable_state_with_caller_or_projection():
    original = payload()
    expected = deepcopy(original)
    plan = MaterializationPlan.from_payload(original)
    original["pricing"]["tools"].append("changed")
    projected = plan.payload()
    projected["pricing"]["tools"].append("changed-again")
    assert plan.payload() == expected
    assert "reservation_id" not in repr(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("version", 2),
        ("unresolved_assets", True),
        ("unresolved_assets", 33),
        ("elapsed_seconds", float("nan")),
        ("library_files", [{"file_id": "private-body"}]),
        ("publications", [{"role": "pdf", "filename": "../private"}]),
    ],
)
def test_invalid_plan_is_bounded(field, value):
    raw = payload()
    raw[field] = value
    with pytest.raises(PreparedCheckpointInvalid) as caught:
        MaterializationPlan.from_payload(raw)
    assert str(caught.value) == "Materialization unavailable"


@pytest.mark.asyncio
async def test_recovery_preserves_registered_publication_without_provider_or_upload():
    raw = payload()
    raw["workspace_id"] = "workspace-fixture"
    raw["expires_at"] = 2000000000
    raw["publications"] = [
        {
            "build_id": "build-fixture",
            "artifact_id": "artifact-fixture",
            "role": "pdf",
            "source_digest": "a" * 64,
            "artifact_sha256": "b" * 64,
            "artifact_size": 40,
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "initial_status": "pending_delivery",
        }
    ]
    files = SimpleNamespace(fetch_file_metadata=AsyncMock(), save_stream=AsyncMock())
    result = await recover_materialization(
        MaterializationPlan.from_payload(raw), owner_id=str(uuid4()), file_service=files
    )
    assert result["metadata"]["_document_publications"] == raw["publications"]
    assert result["workspace_ref"]["workspace_id"] == raw["workspace_id"]
    assert result["reservation_id"] == raw["reservation_id"]
    files.fetch_file_metadata.assert_not_awaited()
    files.save_stream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [False, True])
async def test_missing_owned_file_cannot_be_reported_as_recovered(mismatch):
    raw = payload()
    raw["library_files"] = [
        {
            "file_id": str(uuid4()),
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "kind": "pdf",
        }
    ]
    returned = SimpleNamespace(file_id=uuid4()) if mismatch else None
    files = SimpleNamespace(fetch_file_metadata=AsyncMock(return_value=returned))
    with pytest.raises(JobStateUnavailable):
        await recover_materialization(
            MaterializationPlan.from_payload(raw), owner_id=str(uuid4()), file_service=files
        )


@pytest.mark.asyncio
async def test_lost_binary_buffer_is_unresolved_not_a_phantom_download():
    raw = payload()
    raw["unresolved_assets"] = 1
    files = SimpleNamespace(fetch_file_metadata=AsyncMock(), save_stream=AsyncMock())
    with pytest.raises(JobStateUnavailable):
        await recover_materialization(
            MaterializationPlan.from_payload(raw), owner_id=str(uuid4()), file_service=files
        )
    files.fetch_file_metadata.assert_not_awaited()
    files.save_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_requires_exact_owner_and_file_without_private_capability_projection():
    raw = payload()
    owner, file_id = uuid4(), uuid4()
    raw["library_files"] = [
        {
            "file_id": str(file_id),
            "filename": "document.pdf",
            "mime_type": "application/pdf",
            "kind": "pdf",
        }
    ]
    files = SimpleNamespace(
        fetch_file_metadata=AsyncMock(
            return_value=SimpleNamespace(
                file_id=file_id, file_key="PRIVATE_STORAGE_KEY", file_url="PRIVATE_CAPABILITY"
            )
        )
    )
    result = await recover_materialization(
        MaterializationPlan.from_payload(raw), owner_id=str(owner), file_service=files
    )
    files.fetch_file_metadata.assert_awaited_once_with(owner, file_id)
    assert result["metadata"]["generated_files"] == raw["library_files"]
    assert "PRIVATE" not in repr(result)
