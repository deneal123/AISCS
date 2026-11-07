import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.synaptic_replay import (
    execute_all_incoming_replay,
    execute_reference_replay,
    execute_registered_replay,
    read_verified_spikes,
    replay_evidence_json,
    schedule_candidate_events,
    select_recorded_spikes,
)


def run(mapping, spikes, **overrides):
    settings = {"delay_ms": 2., "duration_ms": 10., "weight_us": .001,
                "tau1_ms": .2, "tau2_ms": 2., "reversal_mv": 0.}
    settings.update(overrides)
    return schedule_candidate_events(mapping, spikes, **settings)


def test_selects_graph_indices_without_confusing_them_with_cell_ids():
    selected = select_recorded_spikes(np.array([11, 12, 42]), np.array([2, 0, 2]),
                                      np.array([3., 4., 5.]), [42])
    assert selected == {"42": [3., 5.]}
    assert select_recorded_spikes(np.array([11, 42]), np.array([1]), np.array([2.]),
                                  [11, 42]) == {"11": [], "42": [2.]}
    with pytest.raises(ValueError, match="missing from graph"):
        select_recorded_spikes(np.array([11, 12, 42]), np.array([2]), np.array([1.]), [13])
    with pytest.raises(ValueError, match="spike stream"):
        select_recorded_spikes(np.array([11, 12, 42]), np.array([3]), np.array([1.]), [42])
    with pytest.raises(ValueError, match="spike stream"):
        select_recorded_spikes(np.array([11, 42]), np.array([0, 1]), np.array([3., 2.]), [42])
    with pytest.raises(ValueError, match="partner IDs"):
        select_recorded_spikes(np.array([11]), np.array([0]), np.array([1.]), [[11]])


def test_saved_spike_buffer_requires_matching_hash_layout_and_graph():
    ids = np.array([11, 42], dtype='<u8')
    indices = np.array([1, 0], dtype='<i4')
    times = np.array([3., 4.], dtype='<f4')
    binary = ids.tobytes() + indices.tobytes() + times.tobytes()
    arrays = {
        'node_ids': {'offset': 0, 'dtype': '<u8', 'count': 2, 'shape': [2]},
        'spike_neurons': {'offset': 16, 'dtype': '<i4', 'count': 2, 'shape': [2]},
        'spike_times_ms': {'offset': 24, 'dtype': '<f4', 'count': 2, 'shape': [2]},
    }
    description = {'manifest_sha256': 'graph', 'duration_ms': 10., 'binary': {
        'bytes': len(binary), 'byte_order': 'little', 'arrays': arrays}}
    sha = hashlib.sha256(binary).hexdigest()
    assert read_verified_spikes(binary, description, sha, ids, 'graph', [42]) == {'42': [3.]}
    with pytest.raises(ValueError, match='checksum'):
        read_verified_spikes(binary, description, 'a' * 64, ids, 'graph', [42])
    with pytest.raises(ValueError, match='version'):
        read_verified_spikes(binary, description, sha, ids, 'wrong', [42])
    with pytest.raises(ValueError, match='duration'):
        read_verified_spikes(binary, {**description, 'duration_ms': 2.}, sha, ids, 'graph', [42])
    with pytest.raises(ValueError, match='node IDs'):
        read_verified_spikes(binary, description, sha, np.array([11, 43]), 'graph', [42])
    broken = {**description, 'binary': {**description['binary'], 'arrays': {
        **arrays, 'spike_times_ms': {**arrays['spike_times_ms'], 'offset': 16}}}}
    with pytest.raises(ValueError, match='overlap'):
        read_verified_spikes(binary, broken, sha, ids, 'graph', [42])


def test_replay_uses_presynaptic_id_location_and_explicit_delay():
    mapping = {"direction": "incoming", "candidates": [
        {"partner_id": "11", "child_node_id": 2, "segment_fraction": .4},
        {"partner_id": "11", "child_node_id": 3, "segment_fraction": .7},
        {"partner_id": "12", "child_node_id": 4, "segment_fraction": .2},
    ]}
    result = run(mapping, {"11": [1., 9.], "12": [2.], "13": [3.]})
    assert [(e["child_node_id"], e["time_ms"]) for e in result["events"]] == [
        (2, 3.), (3, 3.), (4, 4.)
    ]
    assert result["outside_window"] == 2
    assert result["events"][0]["position"] == .4
    assert result["events"][0]["weight_us"] == .001
    assert result["event_sources"] == [
        {"candidate_index": 0, "presynaptic_id": "11", "spike_index": 0, "spike_time_ms": 1.},
        {"candidate_index": 1, "presynaptic_id": "11", "spike_index": 0, "spike_time_ms": 1.},
        {"candidate_index": 2, "presynaptic_id": "12", "spike_index": 0, "spike_time_ms": 2.},
    ]


def test_overflow_and_invalid_inputs_fail_without_truncation():
    mapping = {"direction": "incoming", "candidates": [
        {"partner_id": "11", "child_node_id": 2, "segment_fraction": .5}]}
    with pytest.raises(ValueError, match="event limit"):
        run(mapping, {"11": [1., 2.]}, max_events=1)
    with pytest.raises(ValueError, match="incoming"):
        run({**mapping, "direction": "outgoing"}, {"11": [1.]})
    with pytest.raises(ValueError, match="spike"):
        run(mapping, {"11": [float('nan')]})
    with pytest.raises(ValueError, match="parameters"):
        run(mapping, {"11": [1.]}, weight_us=True)
    with pytest.raises(ValueError, match="parameters"):
        run(mapping, {"11": [1.]}, tau1_ms=1.99999, tau2_ms=2.)
    with pytest.raises(ValueError, match="parameters"):
        run(mapping, {"11": [1.]}, tau1_ms=1e-12, tau2_ms=2.)
    with pytest.raises(ValueError, match="Missing recorded spike"):
        run(mapping, {})


def test_per_partner_parameters_must_be_explicit_and_complete():
    mapping = {"direction": "incoming", "candidates": [
        {"partner_id": "11", "child_node_id": 2, "segment_fraction": .5},
        {"partner_id": "12", "child_node_id": 3, "segment_fraction": .5},
    ]}
    params = {"11": {"weight_us": .001, "tau1_ms": .2, "tau2_ms": 2., "reversal_mv": 0.},
              "12": {"weight_us": .002, "tau1_ms": .3, "tau2_ms": 3., "reversal_mv": -80.}}
    result = run(mapping, {"11": [1.], "12": [1.]}, partner_parameters=params)
    assert [event["reversal_mv"] for event in result["events"]] == [0., -80.]
    with pytest.raises(ValueError, match="Missing synaptic parameters"):
        run(mapping, {"11": [1.], "12": []}, partner_parameters={"11": params["11"]})
    with pytest.raises(ValueError, match="Invalid per-partner"):
        run(mapping, {"11": [1.], "12": []}, partner_parameters={"11": {"weight_us": .001}})


def test_replay_events_drive_independent_compartment():
    pytest.importorskip("neuron")
    from service.infrastructure.stimulation.swc_reference import simulate_swc_reference

    swc = "1 1 0 0 0 62.5 -1\n2 3 12500 0 0 62.5 1\n"
    mapping = {"direction": "incoming", "candidates": [
        {"partner_id": "11", "child_node_id": 2, "segment_fraction": .5}]}
    events = run(mapping, {"11": [2.]})["events"]
    args = (swc, [0, 100, 0], [200, 100, 0], 0, .3)
    baseline = simulate_swc_reference(*args, clearance_um=2)
    replay = simulate_swc_reference(*args, clearance_um=2, synaptic_events=events)
    assert max(abs(replay["voltage_mv"][0] - baseline["voltage_mv"][0])) > .01


def test_complete_reference_replay_binds_mapping_to_source(tmp_path):
    pytest.importorskip("neuron")
    from service.infrastructure.connectome.morphology_repository import BASE

    swc = "1 1 0 0 0 62.5 -1\n2 3 12500 0 0 62.5 1\n"
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    (tmp_path / "raw/42.swc").write_text(swc)
    sha = hashlib.sha256(swc.encode()).hexdigest()
    (tmp_path / "receipts/42.json").write_text(json.dumps({
        "body_id": 42, "sha256": sha, "url": BASE + "42.swc",
    }))
    mapping = {"body_id": "42", "morphology_sha256": sha, "direction": "incoming",
               "candidates": [{"partner_id": "11", "child_node_id": 2,
                               "segment_fraction": .5}]}
    schedule = {"delay_ms": 2., "duration_ms": 10., "weight_us": .001,
                "tau1_ms": .2, "tau2_ms": 2., "reversal_mv": 0.}
    simulation = {"source_um": [0, 100, 0], "return_um": [200, 100, 0],
                  "current_na": 0, "conductivity_s_m": .3, "clearance_um": 2,
                  "duration_ms": 10.}
    kwargs = {"schedule_parameters": schedule, "simulation_parameters": simulation,
              "electrode_um": [0, 200, 0], "reference_um": [200, 200, 0]}
    result = execute_reference_replay(mapping, {"11": [2.]}, [tmp_path], **kwargs)
    assert result["provenance"]["morphology_sha256"] == sha
    assert result["replay"]["events"][0]["time_ms"] == 4.
    assert result["recording_configuration"]["electrode_um"] == [0., 200., 0.]
    assert result["recording_configuration"]["reference_um"] == [200., 200., 0.]
    assert result["recording_configuration"]["conductivity_s_m"] == .3
    assert np.isfinite(result["channel"]["total_uv"]).all()
    swapped = execute_reference_replay(
        mapping, {"11": [2.]}, [tmp_path],
        **{**kwargs, "electrode_um": kwargs["reference_um"],
           "reference_um": kwargs["electrode_um"]},
    )
    np.testing.assert_allclose(swapped["channel"]["total_uv"], -result["channel"]["total_uv"],
                               atol=1e-12)
    with pytest.raises(ValueError, match="morphology differ"):
        execute_reference_replay({**mapping, "morphology_sha256": "wrong"},
                                 {"11": [2.]}, [tmp_path], **kwargs)
    with pytest.raises(ValueError, match="durations"):
        execute_reference_replay(
            mapping, {"11": [2.]}, [tmp_path],
            **{**kwargs, "schedule_parameters": {**schedule, "duration_ms": 9.}},
        )


def test_registered_replay_verifies_buffer_and_limits_window(monkeypatch):
    ids = np.array([11, 42], dtype='<u8')
    indices = np.array([0, 0], dtype='<i4')
    times = np.array([3., 40.], dtype='<f4')
    binary = ids.tobytes() + indices.tobytes() + times.tobytes()
    arrays = {
        'node_ids': {'offset': 0, 'dtype': '<u8', 'count': 2, 'shape': [2]},
        'spike_neurons': {'offset': 16, 'dtype': '<i4', 'count': 2, 'shape': [2]},
        'spike_times_ms': {'offset': 24, 'dtype': '<f4', 'count': 2, 'shape': [2]},
    }
    description = {'manifest_sha256': 'graph', 'duration_ms': 100, 'binary': {
        'bytes': len(binary), 'byte_order': 'little', 'arrays': arrays}}
    mapping = {'direction': 'incoming', 'candidates': [{'partner_id': '11'}]}
    monkeypatch.setattr('service.infrastructure.connectome.synapse_morphology.registered_page_candidates',
                        lambda *args: mapping)
    monkeypatch.setattr('service.infrastructure.stimulation.synaptic_replay.execute_reference_replay',
                        lambda target, spikes, *args, **kwargs: {'replayed': spikes})
    graph = SimpleNamespace(ids=ids, provenance={'manifest_sha256': 'graph'})
    args = (None, graph, 42, 0, 20, [])
    kwargs = {'binary': binary, 'description': description,
              'expected_sha256': hashlib.sha256(binary).hexdigest(),
              'schedule_parameters': {'duration_ms': 20.},
              'simulation_parameters': {'duration_ms': 20.},
              'electrode_um': [0, 0, 0], 'reference_um': [1, 0, 0]}
    result = execute_registered_replay(*args, **kwargs)
    assert result['replayed'] == {'11': [3.]}
    assert result['spikes_after_replay_window'] == 1
    with pytest.raises(ValueError, match='checksum'):
        execute_registered_replay(*args, **{**kwargs, 'expected_sha256': 'a' * 64})
    with pytest.raises(ValueError, match='duration'):
        execute_registered_replay(*args, **{**kwargs, 'schedule_parameters': {'duration_ms': 101.}})


def test_all_incoming_replay_consumes_every_page(monkeypatch):
    common = {'body_id': '42', 'direction': 'incoming', 'source_md5': 'source',
              'morphology_sha256': 'skeleton', 'graph_manifest_sha256': 'graph',
              'source_coordinate_frame': '8nm'}
    calls = []
    def single_pass(index, graph, body_id, directories, *, candidate_partner_ids, progress):
        assert candidate_partner_ids == {11}
        calls.extend([0, 20])
        progress(1, 0, 20)
        progress(2, 20, None)
        return {**common, 'complete_graph_edge_coverage': True,
                'candidates': [{'partner_id': '11'}, {'partner_id': '12'}]}
    monkeypatch.setattr('service.infrastructure.connectome.synapse_morphology.'
                        'registered_incoming_candidates_single_pass', single_pass)
    monkeypatch.setattr('service.infrastructure.stimulation.synaptic_replay._execute_mapping_replay',
                        lambda mapping, *args, **kwargs: mapping)
    monkeypatch.setattr('service.infrastructure.stimulation.synaptic_replay._read_verified_spike_arrays',
                        lambda *args: (np.array([0]), np.array([1.])))
    progress = []
    graph = SimpleNamespace(ids=np.array([11, 12]), provenance={'manifest_sha256': 'graph'})
    result = execute_all_incoming_replay(
        None, graph, 42, [], binary=b'', description={'duration_ms': 10}, expected_sha256='hash',
        schedule_parameters={'duration_ms': 10, 'delay_ms': 2}, simulation_parameters={},
        electrode_um=[], reference_um=[],
        progress=lambda *args: progress.append(args),
    )
    assert calls == [0, 20]
    assert result['complete_graph_edge_coverage']
    assert [item['partner_id'] for item in result['candidates']] == ['11', '12']
    assert progress == [(1, 0, 20), (2, 20, None)]


def test_evidence_serializes_events_and_rejects_missing_or_nonfinite_metadata():
    record = {'mapping': {'body_id': '42'}, 'selected_spikes': {'11': [3.]},
              'spikes_after_replay_window': 0, 'connectome_sha256': 'a' * 64,
              'provenance': {'configuration': {'duration_ms': 10.}},
              'replay': {'events': [{'time_ms': 5.}], 'event_sources': [{'presynaptic_id': '11'}]},
              'recording_configuration': {'electrode_um': [0., 1., 2.]},
              'interpretation': 'one-way replay'}
    first = replay_evidence_json(record)
    assert first == replay_evidence_json(dict(reversed(list(record.items()))))
    assert json.loads(first)['replay']['event_sources'][0]['presynaptic_id'] == '11'
    with pytest.raises(ValueError, match='Incomplete'):
        replay_evidence_json({})
    with pytest.raises(ValueError, match='finite JSON'):
        replay_evidence_json({**record, 'selected_spikes': {'11': [float('nan')]}})
