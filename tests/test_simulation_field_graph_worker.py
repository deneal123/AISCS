import hashlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.services.simulations import tasks
from service.services.simulations.models import SimulationArtifact
from tests.test_simulation_field_graph_manifest import configuration, preview


@pytest.mark.asyncio
async def test_worker_preserves_safe_contact_failure_code(monkeypatch):
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(id=run_id, user_id=owner, attempt_id=attempt, job_id=uuid4(),
                          state="queued", execution_queue="simulation", lease_until=None,
                          configuration=configuration(),
                          configuration_sha256="a" * 64, claim_token=None)
    job = SimpleNamespace(status=None)

    class Session:
        async def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: run)

        async def get(self, *_args):
            return job

        async def commit(self):
            pass

    @asynccontextmanager
    async def session_context():
        yield Session()

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=session_context,
                                                         close=AsyncMock()), redis_client=None)
    monkeypatch.setattr(tasks, "build_infra", lambda _config: infra)
    monkeypatch.setattr(tasks, "emit", AsyncMock())
    touch = AsyncMock(return_value=False)
    monkeypatch.setattr(tasks, "touch", touch)
    monkeypatch.setattr(tasks, "discard_unpublished", AsyncMock())

    async def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(200, json={"status": "failed", "error": {
            "type": "ValueError",
            "message": "Contact exclusion sphere intersects a cable segment"}})

    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="http://generator") as session:
            yield session

    monkeypatch.setattr(tasks, "generator_client", client)
    await tasks.execute(run_id)
    assert any(call.kwargs.get("error") == "executor_contact_clearance"
               for call in touch.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("tampered", ["none", "preview", "archive"])
@pytest.mark.parametrize("retain_currents", [False, True])
async def test_field_graph_worker_publishes_only_verified_preview(
    monkeypatch, tampered, retain_currents
):
    if tampered == "archive" and not retain_currents:
        pytest.skip("No current archive exists in this configuration")
    run_id, attempt, owner = uuid4(), uuid4(), uuid4()
    digest = "a" * 64
    run = SimpleNamespace(
        id=run_id,
        user_id=owner,
        attempt_id=attempt,
        job_id=uuid4(),
        state="queued",
        execution_queue="simulation",
        lease_until=None,
        configuration=configuration(),
        configuration_sha256=digest,
        claim_token=None,
    )
    job, saved_rows = SimpleNamespace(status=None), []
    if retain_currents:
        run.configuration["retain_currents"] = True

    class Session:
        async def execute(self, statement):
            value = None if "simulation_artifact" in str(statement) else run
            return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value)

        async def get(self, *_args):
            return job

        def add(self, value):
            saved_rows.append(value)

        async def commit(self):
            pass

    @asynccontextmanager
    async def session_context():
        yield Session()

    connector = SimpleNamespace(get_session_context=session_context, close=AsyncMock())
    infra = SimpleNamespace(pg_connector=connector, redis_client=None, storage=object())
    monkeypatch.setattr(tasks, "build_infra", lambda _config: infra)
    monkeypatch.setattr(tasks, "emit", AsyncMock())
    stage, ack, reject = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(tasks, "stage_replay_input", stage)
    monkeypatch.setattr(tasks, "acknowledge_result", ack)
    monkeypatch.setattr(tasks, "reject_result", reject)
    publications = []

    async def touch(_infra, _id, _token, state=None, result=None, **_kwargs):
        if state:
            run.state = state
        if result:
            publications.append(result)
        return False

    monkeypatch.setattr(tasks, "touch", touch)
    files = {
        name: b"data"
        for name in (
            "graph.bin",
            "replay-evidence.jsonl",
            "replay-provenance.jsonl",
            "metadata.json",
            "signals.npz",
        )
    }
    files["field-graph-preview.json"] = json.dumps(preview(), ensure_ascii=False).encode()
    if retain_currents:
        files["currents.zip"] = b"verified current archive"
    manifest = {
        "format": "field-graph-replay-manifest-v1",
        "kind": "field-graph-replay",
        "configuration_sha256": digest,
        "files": [
            {"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ],
    }
    if retain_currents:
        manifest["current_manifest_sha256"] = "c" * 64
    preview_requests = 0

    async def handler(request):
        nonlocal preview_requests
        if request.method == "POST":
            assert request.url.path == "/v1/field-graph-executions"
            sent = json.loads(request.content)["config"]
            assert sent.get("retain_currents", False) is retain_currents
            return httpx.Response(200, json={"status": "running"})
        if request.url.path.endswith(str(attempt)):
            return httpx.Response(200, json={"status": "completed", "manifest": manifest})
        name = request.url.path.rsplit("/", 1)[-1]
        if tampered == "archive" and name == "currents.zip":
            return httpx.Response(200, content=b"tampered current archive")
        if name == "field-graph-preview.json":
            preview_requests += 1
            if tampered == "preview" and preview_requests == 2:
                return httpx.Response(200, content=b"tampered")
        return httpx.Response(200, content=files[name])

    @asynccontextmanager
    async def client_factory():
        async with httpx.AsyncClient(
            base_url="http://generator", transport=httpx.MockTransport(handler)
        ) as client:
            yield client

    monkeypatch.setattr(tasks, "generator_client", client_factory)

    async def save(_owner, _kind, name, chunks, **kwargs):
        await kwargs["before_persist"]()
        data = b"".join([part async for part in chunks])
        if len(data) != kwargs["expected_size"] or (
            hashlib.sha256(data).hexdigest() != kwargs["expected_sha256"]
        ):
            raise ValueError("artifact_integrity")
        return SimpleNamespace(file_id=uuid4())

    monkeypatch.setattr(tasks, "file_service", lambda _infra: SimpleNamespace(save_stream=save))
    await tasks.execute(run_id)
    stage.assert_not_awaited()
    saved = {row.name for row in saved_rows if isinstance(row, SimulationArtifact)}
    if tampered == "archive":
        assert saved == set(files) - {"currents.zip"}
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == "artifact_integrity"
    elif tampered == "preview":
        assert saved == set(files)
        assert not publications
        ack.assert_not_awaited()
        assert reject.await_args.args[-1] == "preview_integrity"
    else:
        assert saved == set(files)
        assert run.state == "completed"
        assert publications[0]["preview"]["acquisition"]["saturated_samples"][1]
        ack.assert_awaited_once()
        reject.assert_not_awaited()
