import hashlib
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from service.services.simulations.inputs.current_source import (
    CurrentSource,
    CurrentSourceUnavailable,
    owned_current_source,
)
from service.services.simulations.rerecord import (
    RerecordError,
    transfer_rerecord,
    validate_rerecord_preview,
)
from tests.test_simulation_field_graph_manifest import manifest
from tests.test_simulation_replay_source import Session


def source(data=b"archive"):
    return CurrentSource(
        "owned/zip",
        hashlib.sha256(data).hexdigest(),
        len(data),
        "c" * 64,
        {
            "simulation": {"duration_ms": 2, "dt_ms": 1, "source_model": "pointsource"},
            "source_cells": [{"body_id": 1}],
            "replay_ids": [2],
        },
    )


@pytest.mark.asyncio
async def test_owned_current_source_requires_owned_run_and_matching_file():
    record = manifest()
    record["current_manifest_sha256"] = "c" * 64
    record["files"].append({"name": "currents.zip", "bytes": 7, "sha256": "b" * 64})
    run = SimpleNamespace(
        state="completed",
        configuration={"retain_currents": True},
        configuration_sha256="a" * 64,
        result={"manifest": record},
    )
    file_id = uuid4()
    row = (
        SimpleNamespace(sha256="b" * 64, size=7, file_id=file_id),
        SimpleNamespace(id=file_id, file_name="owned/zip"),
    )
    session = Session(run, row)
    found = await owned_current_source(session, uuid4(), uuid4())
    assert found.manifest_sha256 == "c" * 64
    assert "simulation_run.user_id" in str(session.statements[0])
    assert "user_file.user_id" in str(session.statements[1])
    row[0].sha256 = "d" * 64
    with pytest.raises(CurrentSourceUnavailable):
        await owned_current_source(Session(run, row), uuid4(), uuid4())
    with pytest.raises(CurrentSourceUnavailable):
        await owned_current_source(Session(None, row), uuid4(), uuid4())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_storage,bad_preview",
    [
        (False, None),
        (True, None),
        (False, "sum"),
        (False, "time"),
        (False, "stimulus"),
    ],
)
async def test_transfer_verifies_archive_and_returned_preview(bad_storage, bad_preview):
    item = source()
    e1, ref = [0.0, 1.0, 2.0], [3.0, 4.0, 5.0]
    preview = {
        "time_ms": [0.0, 1.0, 2.0],
        "neural_uv": [1.0, 2.0, 3.0],
        "stimulus_artifact_uv": [0.0, 1.0, 0.0],
        "total_uv": [1.0, 3.0, 3.0],
        "stimulus_fraction": [0.0, 1.0, 0.0],
        "samples": 3,
        "shown_samples": 3,
        "cells": 2,
        "electrode_um": e1,
        "reference_um": ref,
        "package_sha256": item.sha256,
        "current_manifest_sha256": item.manifest_sha256,
        "source_model": "pointsource",
        "coordinate_frame": "MaleCNS native EM, micrometres",
        "interpretation": "rerecording selected independent cells; no whole-network currents",
    }
    if bad_preview == "sum":
        preview["total_uv"][1] = 99
    elif bad_preview == "time":
        preview["time_ms"][1] = 0.5
    elif bad_preview == "stimulus":
        preview["stimulus_fraction"][1] = 1.2

    class Storage:
        async def download_file_stream(self, *, file_key, target, max_bytes):
            assert file_key == "owned/zip" and max_bytes == 7
            data = b"corrupt" if bad_storage else b"archive"
            target.write(data)
            return len(data)

    async def handler(request):
        assert await request.aread() == b"archive"
        assert request.extensions["timeout"]["read"] == 120.0
        return httpx.Response(200, json=preview)

    async with httpx.AsyncClient(
        base_url="http://generator", transport=httpx.MockTransport(handler)
    ) as client:
        if bad_storage or bad_preview:
            with pytest.raises(RerecordError):
                await transfer_rerecord(Storage(), client, item, e1, ref)
        else:
            assert await transfer_rerecord(Storage(), client, item, e1, ref) == preview


def test_rerecord_rejects_incomplete_or_contradictory_acquisition_mask():
    item = source()
    item.configuration["acquisition"] = {"low_hz": 1, "high_hz": 100, "recovery_ms": 0}
    e1, ref = [0.0, 1.0, 2.0], [3.0, 4.0, 5.0]
    preview = {
        "time_ms": [0.0, 1.0, 2.0],
        "neural_uv": [1.0, 2.0, 3.0],
        "stimulus_artifact_uv": [0.0, 1.0, 0.0],
        "total_uv": [1.0, 3.0, 3.0],
        "stimulus_fraction": [0.0, 1.0, 0.0],
        "samples": 3,
        "shown_samples": 3,
        "cells": 2,
        "electrode_um": e1,
        "reference_um": ref,
        "package_sha256": item.sha256,
        "current_manifest_sha256": item.manifest_sha256,
        "source_model": "pointsource",
        "coordinate_frame": "MaleCNS native EM, micrometres",
        "interpretation": "rerecording selected independent cells; no whole-network currents",
        "acquisition": {
            "filtered_total_uv": [0.0, 1.0, 0.0],
            "valid_samples": [True, False, False],
            "saturated_samples": [False, True, False],
            "settings": {"low_hz": 1, "high_hz": 100, "recovery_ms": 0},
            "mask_scope": "conservative aggregation over the source bin",
            "mask_intervals": [
                {"start_ms": 0.0, "end_ms": 0.5, "valid": True, "saturated": False},
                {"start_ms": 0.5, "end_ms": 1.5, "valid": False, "saturated": True},
                {"start_ms": 1.5, "end_ms": 2.0, "valid": False, "saturated": False},
            ],
        },
    }
    validate_rerecord_preview(preview, item, e1, ref)
    preview["acquisition"]["mask_intervals"][1]["start_ms"] = 0.6
    with pytest.raises(RerecordError):
        validate_rerecord_preview(preview, item, e1, ref)
    preview["acquisition"]["mask_intervals"][1]["start_ms"] = 0.5
    preview["acquisition"]["mask_intervals"][1]["valid"] = True
    with pytest.raises(RerecordError):
        validate_rerecord_preview(preview, item, e1, ref)
