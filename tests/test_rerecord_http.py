import asyncio
import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("neuron")

from service.infrastructure.stimulation.current_archive import write_current_archive  # noqa: E402
from service.infrastructure.stimulation.current_transport import pack_current_archive  # noqa: E402
from service.main import create_app  # noqa: E402
from tests.test_network_recording import pair  # noqa: E402


def test_rerecord_requires_auth_and_valid_hashes_and_cleans_workspace(tmp_path):
    e1, ref = [0, 200, 0], [200, 200, 0]
    archive, package, root = tmp_path / "archive", tmp_path / "input.zip", tmp_path / "executor"
    digest = write_current_archive([pair(1)], archive, e1, ref)
    info = pack_current_archive(archive, digest, package)
    params = {"package_sha256": info["sha256"], "current_manifest_sha256": digest,
              "electrode_um": e1, "reference_um": ref, "source_model": "pointsource"}
    headers = {"X-Recording-Configuration": json.dumps(params)}
    client = TestClient(create_app(root, "a" * 32))
    assert client.post("/v1/rerecord-preview", content=package.read_bytes(),
                       headers=headers).status_code == 401
    headers["Authorization"] = "Bearer " + "a" * 32
    response = client.post("/v1/rerecord-preview", content=package.read_bytes(), headers=headers)
    assert response.status_code == 200
    assert response.json()["cells"] == 1
    assert not list(root.glob("rerecord-http-*"))
    params["package_sha256"] = "0" * 64
    headers["X-Recording-Configuration"] = json.dumps(params)
    assert client.post("/v1/rerecord-preview", content=package.read_bytes(),
                       headers=headers).status_code == 422
    assert not list(root.glob("rerecord-http-*"))


def test_disconnect_waits_for_worker_before_cleaning_files(tmp_path, monkeypatch):
    from service.application.replay import rerecord_preview

    started, release = threading.Event(), threading.Event()
    root = tmp_path / "executor"
    config = {"package_sha256": "a" * 64, "current_manifest_sha256": "b" * 64,
              "electrode_um": [0, 1, 2], "reference_um": [3, 4, 5],
              "source_model": "pointsource"}

    def worker(package, *_args, **_kwargs):
        started.set()
        assert release.wait(5)
        assert package.read_bytes() == b"archive"
        return {"ok": True}

    monkeypatch.setattr(rerecord_preview, "rerecord_preview", worker)

    async def scenario():
        transport = httpx.ASGITransport(app=create_app(root, "a" * 32))
        async with httpx.AsyncClient(transport=transport, base_url="http://generator") as client:
            task = asyncio.create_task(client.post(
                "/v1/rerecord-preview", content=b"archive", headers={
                    "Authorization": "Bearer " + "a" * 32,
                    "X-Recording-Configuration": json.dumps(config),
                }))
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(.05)
            assert list(root.glob("rerecord-http-*"))
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not list(root.glob("rerecord-http-*"))

    asyncio.run(scenario())
