import numpy as np
import pytest

pytest.importorskip("neuron")

from service.infrastructure.stimulation.network_recording import (
    record_independent_cells,  # noqa: E402
)
from service.infrastructure.stimulation.recording.current_archive import (  # noqa: E402
    CurrentArchiveWriter,
    rerecord_current_archive,
    write_current_archive,
)
from tests.test_forced_network import graph  # noqa: E402
from tests.test_network_recording import pair  # noqa: E402
from tests.test_population_replay import result as replay_result  # noqa: E402


def test_archive_rerecords_same_currents_at_new_contacts_and_detects_tampering(tmp_path):
    cells = [pair(1), pair(2, 1250)]
    e1, ref = [0, 200, 0], [200, 200, 0]
    moved = [0, 300, 0]
    archive = tmp_path / "currents"
    digest = write_current_archive(iter(cells), archive, e1, ref)
    same = rerecord_current_archive(archive, digest, e1, ref)
    new = rerecord_current_archive(archive, digest, moved, ref)
    expected = record_independent_cells(iter(cells), moved, ref)
    np.testing.assert_allclose(new["neural_uv"], expected["neural_uv"], rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(new["total_uv"], expected["total_uv"], rtol=1e-12, atol=1e-12)
    assert not np.array_equal(new["neural_uv"], same["neural_uv"])
    assert new["cells"] == 2 and new["current_archive_sha256"] == digest
    assert new["ordered_sources_sha256"] == expected["ordered_sources_sha256"]
    source = archive / "cell-000000.npz"
    source.write_bytes(source.read_bytes()[:-1] + b"x")
    with pytest.raises(ValueError, match="checksum"):
        rerecord_current_archive(archive, digest, moved, ref)


def test_archive_rejects_duplicates_and_mismatched_manifest(tmp_path):
    cell = pair(1)
    e1, ref = [0, 200, 0], [200, 200, 0]
    with pytest.raises(ValueError, match="Duplicate"):
        write_current_archive([cell, cell], tmp_path / "duplicate", e1, ref)
    archive = tmp_path / "valid"
    write_current_archive([cell], archive, e1, ref)
    with pytest.raises(ValueError, match="manifest mismatch"):
        rerecord_current_archive(archive, "0" * 64, e1, ref)


def test_archive_detects_change_during_read(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.recording import current_archive as current_archive

    e1, ref = [0, 200, 0], [200, 200, 0]
    archive = tmp_path / "source"
    digest = write_current_archive([pair(1)], archive, e1, ref)
    original = current_archive._stream_sha
    calls = 0

    def changed(stream):
        nonlocal calls
        calls += 1
        return original(stream) if calls == 1 else "0" * 64

    monkeypatch.setattr(current_archive, "_stream_sha", changed)
    with pytest.raises(ValueError, match="changed during reading"):
        rerecord_current_archive(archive, digest, e1, ref)


def test_field_graph_streams_source_and_replay_currents_into_one_archive(tmp_path, monkeypatch):
    from service.application.field.graph_replay import run_field_graph_replay

    cells = {10: pair(10), 20: pair(20, 1250)}
    monkeypatch.setattr(
        "service.application.field.driven_network.simulate_registered_swc_reference",
        lambda body, *_args, **_kwargs: cells[body],
    )

    def replay(_index, _graph, body, _directories, **kwargs):
        result = replay_result(body, cells[body])
        result["connectome_sha256"] = kwargs["expected_sha256"]
        return result

    monkeypatch.setattr("service.application.replay.population_replay._execute_preverified_incoming_replay",
                        replay)
    e1, ref = [0, 200, 0], [200, 200, 0]
    writer = CurrentArchiveWriter(tmp_path / "stream", e1, ref)
    result = run_field_graph_replay(
        None,
        graph(),
        [],
        source_cells=[{"body_id": 10, "child_node_id": 2, "threshold_mv": 1000}],
        replay_ids=[20],
        simulation_parameters={"duration_ms": 10},
        schedule_parameters={"duration_ms": 10, "delay_ms": 0},
        recording={"electrode_um": e1, "reference_um": ref, "source_model": "pointsource"},
        seed=1,
        solution_sink=writer.add,
    )
    digest = writer.finish()
    recovered = rerecord_current_archive(tmp_path / "stream", digest, e1, ref)
    np.testing.assert_allclose(recovered["total_uv"], result["recording"]["total_uv"])
    assert recovered["cells"] == 2
    with pytest.raises(ValueError, match="closed"):
        writer.add(*cells[10])


def test_writer_refuses_to_finalize_after_failed_cell(tmp_path):
    cell = pair(1)
    writer = CurrentArchiveWriter(tmp_path / "failed", [0, 200, 0], [200, 200, 0])
    writer.add(*cell)
    with pytest.raises(ValueError, match="Duplicate"):
        writer.add(*cell)
    with pytest.raises(ValueError, match="incomplete"):
        writer.finish()
    assert not (tmp_path / "failed" / "manifest.json").exists()


def test_execution_opt_in_checks_archive_against_result_before_publication(tmp_path, monkeypatch):
    from service.application.field.graph_execution import FieldGraphExecution
    from service.domain.contracts.field.graph import FieldGraphConfig
    from tests.test_field_graph_contract import payload

    cells = [pair(10), pair(20, 1250)]
    e1, ref = [0, 200, 0], [200, 200, 0]
    raw = payload()
    raw["simulation"].update(
        source_um=[0, 100, 0],
        return_um=[200, 100, 0],
        electrode_um=e1,
        reference_um=ref,
        clearance_um=2,
    )
    model = graph()
    model.provenance["manifest_sha256"] = raw["graph_manifest_sha256"]
    config = FieldGraphConfig.model_validate(raw)
    recording = record_independent_cells(cells, e1, ref)

    def run(_index, _graph, _directories, **kwargs):
        for solution, provenance in cells:
            kwargs["solution_sink"](solution, provenance)
        return {"recording": recording, "interpretation": "one-way"}

    monkeypatch.setattr("service.application.field.graph_execution.run_field_graph_replay", run)
    monkeypatch.setattr(
        "service.application.field.graph_execution.export_field_graph_replay",
        lambda *_args, **_kwargs: {"files": []},
    )
    monkeypatch.setattr(
        "service.application.field.graph_execution.load_verified_field_graph_replay",
        lambda *_args: None,
    )
    execution = FieldGraphExecution(model, None, [])
    output = execution.execute(
        config, tmp_path / "result", current_archive_output=tmp_path / "currents"
    )
    assert len(output["current_archive_sha256"]) == 64
    assert (
        rerecord_current_archive(tmp_path / "currents", output["current_archive_sha256"], e1, ref)[
            "cells"
        ]
        == 2
    )
    recording["total_uv"] = recording["total_uv"] + 1
    with pytest.raises(ValueError, match="does not reproduce"):
        execution.execute(
            config, tmp_path / "result2", current_archive_output=tmp_path / "currents2"
        )
    assert not (tmp_path / "result2").exists()
