import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.population.diagnostics import (
    fragment_edge_schedule,
    fragment_output_diagnostics,
    preflight_outgoing_fragment_geometry,
    registered_outgoing_fragment_diagnostics,
)

SWC = "1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 1 1250 0 0 1 -1\n4 3 1250 125 0 1 3\n"


def test_geometry_preflight_checks_all_graph_pairs_before_solving(monkeypatch):
    rows = [
        {"body_post": 5, "x_pre": 62, "y_pre": 0, "z_pre": 0},
        {"body_post": 5, "x_pre": 63, "y_pre": 0, "z_pre": 0},
    ]
    graph = SimpleNamespace(posts=[0], provenance={"array_sha256": {"ids.npy": "ids"}})
    index = SimpleNamespace(
        manifest={"ids_sha256": "ids"},
        query=lambda *_a, **_kw: {"total": 2, "returned": 2, "truncated": False, "pairs": rows},
    )
    module = "service.infrastructure.stimulation.population.diagnostics."
    monkeypatch.setattr(
        module + "read_skeleton", lambda *_a, **_kw: {"swc": SWC, "sha256": "d" * 64}
    )
    monkeypatch.setattr(
        module + "outgoing",
        lambda *_a: {"next_offset": None, "items": [{"target_id": "5", "synapse_count": 2}]},
    )
    monkeypatch.setattr(
        module + "map_fragment_candidates",
        lambda *_a, **_kw: {"centerline_distances_um": [0.5, 2.11748]},
    )
    with pytest.raises(ValueError, match=r"source 1, 1/2 graph synapses outside 2 um"):
        preflight_outgoing_fragment_geometry(index, graph, 1, [], max_distance_um=2)
    partial = preflight_outgoing_fragment_geometry(index, graph, 1, [], max_distance_um=2,
                                                   allow_partial_geometry=True)
    assert partial == {"body_id": 1, "graph_pairs": 2, "morphology_sha256": "d" * 64,
                       "unresolved_graph_pairs": 1, "geometry_complete": False}
    receipt = preflight_outgoing_fragment_geometry(index, graph, 1, [], max_distance_um=3)
    assert receipt == {"body_id": 1, "graph_pairs": 2, "morphology_sha256": "d" * 64}


def test_fragment_edge_schedule_keeps_synapses_local_and_rejects_unknowns():
    row = {
        "included_in_graph": True,
        "partner_id": "5",
        "centerline_distance_um": 0.1,
        "status": "stimulus_only_crossing",
        "stimulated_ticks_ms": [1],
        "control_ticks_ms": [],
    }
    other = {**row, "included_in_graph": False, "partner_id": "6"}
    result = {
        "body_id": "1",
        "graph_sha256": "a" * 64,
        "simulation_sha256": "c" * 64,
        "threshold_mv": -20.0,
        "candidates": [row, row, other],
        "source_pairs": 3,
        "duration_ms": 2,
        "graph_pairs": 2,
    }
    schedule = fragment_edge_schedule(result, max_distance_um=0.2, duration_ms=2)
    assert schedule["edge_events"] == [{"source_id": 1, "target_id": 5, "tick": 1, "count": 2}]
    with pytest.raises(
        ValueError, match=r"source 1, 2/2 graph synapses outside 0.05 um; maximum 0.1 um"
    ):
        fragment_edge_schedule(result, max_distance_um=0.05, duration_ms=2)
    bad = {**result, "candidates": [{**row, "status": "timing_or_trace_ambiguous"}, row, other]}
    with pytest.raises(ValueError, match="threshold"):
        fragment_edge_schedule(bad, max_distance_um=0.2, duration_ms=2)


def test_partial_geometry_retains_unresolved_pairs_without_fabricating_events():
    row = {"included_in_graph": True, "partner_id": "5", "centerline_distance_um": .1,
           "status": "stimulus_only_crossing", "stimulated_ticks_ms": [1],
           "control_ticks_ms": [], "source_position_8nm": [2, 3, 4]}
    unresolved = {**row, "centerline_distance_um": 2.5, "source_position_8nm": [9, 8, 7],
                  "status": "geometry_unresolved", "stimulated_ticks_ms": None,
                  "control_ticks_ms": None}
    result = {"body_id": "1", "graph_sha256": "a" * 64, "simulation_sha256": "c" * 64,
              "threshold_mv": -20., "candidates": [row, unresolved], "source_pairs": 2,
              "duration_ms": 2, "graph_pairs": 2}
    with pytest.raises(ValueError, match="outside"):
        fragment_edge_schedule(result, max_distance_um=2, duration_ms=2)
    schedule = fragment_edge_schedule(result, max_distance_um=2, duration_ms=2,
                                      allow_partial_geometry=True)
    assert schedule["edge_events"] == [{"source_id": 1, "target_id": 5, "tick": 1, "count": 1}]
    assert schedule["geometry_complete"] is False
    assert schedule["resolved_graph_pairs"] == 1
    assert schedule["unresolved_geometry"] == [{"candidate_index": 1, "partner_id": "5",
        "centerline_distance_um": 2.5, "source_position_8nm": [9, 8, 7]}]
    malformed = {**result, "candidates": [row, {**unresolved, "partner_id": "unknown"}]}
    with pytest.raises(ValueError, match="partner"):
        fragment_edge_schedule(malformed, max_distance_um=2, duration_ms=2,
                               allow_partial_geometry=True)
    fabricated = {**result, "candidates": [row, {**unresolved, "stimulated_ticks_ms": [1]}]}
    with pytest.raises(ValueError, match="cannot have observed events"):
        fragment_edge_schedule(fabricated, max_distance_um=2, duration_ms=2,
                               allow_partial_geometry=True)
    unidentified = {**result, "candidates": [row, {**unresolved, "source_position_8nm": None}]}
    with pytest.raises(ValueError, match="unresolved synapse coordinates"):
        fragment_edge_schedule(unidentified, max_distance_um=2, duration_ms=2,
                               allow_partial_geometry=True)


def test_explicit_control_crossings_route_actual_active_ticks_without_subtraction():
    row = {'included_in_graph': True, 'partner_id': '5', 'centerline_distance_um': .1,
           'status': 'control_crossing', 'stimulated_ticks_ms': [1, 2],
           'control_ticks_ms': [1]}
    result = {'body_id': '1', 'graph_sha256': 'a' * 64, 'simulation_sha256': 'c' * 64,
              'threshold_mv': -20., 'candidates': [row], 'source_pairs': 1,
              'duration_ms': 2, 'graph_pairs': 1}
    with pytest.raises(ValueError, match='threshold'):
        fragment_edge_schedule(result, max_distance_um=2, duration_ms=2)
    schedule = fragment_edge_schedule(result, max_distance_um=2, duration_ms=2,
                                      include_control_crossings=True)
    assert schedule['edge_events'] == [
        {'source_id': 1, 'target_id': 5, 'tick': 1, 'count': 1},
        {'source_id': 1, 'target_id': 5, 'tick': 2, 'count': 1}]
    bad = {**result, 'candidates': [{**row, 'control_ticks_ms': [2, 1]}]}
    with pytest.raises(ValueError, match='threshold'):
        fragment_edge_schedule(bad, max_distance_um=2, duration_ms=2,
                               include_control_crossings=True)


def inputs():
    time = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    active = {
        "time_ms": time,
        "edge_node_ids": np.array([2, 4]),
        "voltage_mv": np.array([[-65, -10, -65, -65, -65], [-65] * 5]),
    }
    quiet = {
        "time_ms": time.copy(),
        "edge_node_ids": np.array([2, 4]),
        "voltage_mv": np.full((2, 5), -65.0),
    }
    config = {"nseg_per_edge": 1, "current_na": -10.0, "duration_ms": 2}
    provenance = {
        "body_id": "1",
        "morphology_sha256": hashlib.sha256(SWC.encode()).hexdigest(),
        "components": 2,
        "configuration": config,
    }
    control = {**provenance, "configuration": {**config, "current_na": 0.0}}
    return active, quiet, provenance, control


def test_local_candidates_are_not_promoted_to_neuronal_events():
    result = fragment_output_diagnostics(
        SWC, [[0.5, 0, 0], [10, 0.5, 0]], *inputs(), threshold_mv=-20.0, duration_ms=2
    )
    assert result["components"] == 2
    assert [item["component_root_id"] for item in result["candidates"]] == [1, 3]
    assert [item["status"] for item in result["candidates"]] == [
        "stimulus_only_crossing",
        "no_crossing",
    ]
    assert result["candidates"][0]["stimulated_ticks_ms"] == [1]
    assert result["candidates"][0]["stimulated_crossing_intervals"] == [
        {"lower_ms": 0.0, "upper_ms": .5, "tick_ms": 1}]
    assert result["candidates"][0]["control_crossing_intervals"] == []
    assert result["candidates"][0]["segment_fraction"] == pytest.approx(0.5)
    assert result["candidates"][0]["max_stimulated_mv"] == -10.0
    assert result["candidates"][0]["max_control_mv"] == -65.0
    assert result["candidates"][0]["max_abs_delta_mv"] == 55.0
    assert "no fragment connectivity" in result["interpretation"]


def test_candidates_follow_explicit_per_edge_resolution():
    active, quiet, proof, control = inputs()
    active['edge_node_ids'] = np.array([2, 2, 2, 4])
    quiet['edge_node_ids'] = active['edge_node_ids'].copy()
    active['voltage_mv'] = np.array([[-65]*5, [-65]*5, [-65, -10, -65, -65, -65], [-65]*5])
    quiet['voltage_mv'] = np.full((4, 5), -65.)
    proof['configuration']['nseg_by_edge'] = {'2': 3}
    control['configuration']['nseg_by_edge'] = {'2': 3}
    result = fragment_output_diagnostics(
        SWC, [[.9, 0, 0], [10, .5, 0]], active, quiet, proof, control,
        threshold_mv=-20., duration_ms=2)
    assert [row['result_segment_index'] for row in result['candidates']] == [2, 3]
    assert result['candidates'][0]['status'] == 'stimulus_only_crossing'
    proof['configuration']['nseg_by_edge'] = {'2': 5}
    control['configuration']['nseg_by_edge'] = {'2': 5}
    with pytest.raises(ValueError, match='segment missing'):
        fragment_output_diagnostics(SWC, [[.9, 0, 0]], active, quiet, proof, control,
                                    threshold_mv=-20., duration_ms=2)


def test_control_can_skip_recording_currents_without_changing_simulation_identity():
    active, quiet, provenance, control = inputs()
    control = {
        **control,
        "configuration": {**control["configuration"], "record_membrane_current": False},
    }
    result = fragment_output_diagnostics(
        SWC, [[0.5, 0, 0]], active, quiet, provenance, control, threshold_mv=-20.0, duration_ms=2
    )
    assert result["candidates"][0]["status"] == "stimulus_only_crossing"


def test_zero_current_requires_identical_pair_and_never_creates_stimulus_only_events():
    active, quiet, provenance, control = inputs()
    provenance = {**provenance, 'configuration': {**provenance['configuration'], 'current_na': 0.0}}
    with pytest.raises(ValueError, match='Zero-current paired solutions differ'):
        fragment_output_diagnostics(SWC, [[0.5, 0, 0]], active, quiet, provenance, control,
                                    threshold_mv=-20.0, duration_ms=2)
    active['voltage_mv'] = quiet['voltage_mv'].copy()
    result = fragment_output_diagnostics(SWC, [[0.5, 0, 0]], active, quiet, provenance, control,
                                         threshold_mv=-20.0, duration_ms=2)
    assert result['candidates'][0]['status'] == 'no_crossing'
    assert result['candidates'][0]['max_abs_delta_mv'] == 0.0


def test_mismatch_and_ambiguous_sample_fail_safely():
    active, quiet, provenance, control = inputs()
    with pytest.raises(ValueError, match="digest"):
        fragment_output_diagnostics(
            SWC,
            [[0.5, 0, 0]],
            active,
            quiet,
            {**provenance, "morphology_sha256": "0" * 64},
            control,
            threshold_mv=-20.0,
            duration_ms=2,
        )
    with pytest.raises(ValueError, match="configurations"):
        fragment_output_diagnostics(
            SWC,
            [[0.5, 0, 0]],
            active,
            quiet,
            provenance,
            provenance,
            threshold_mv=-20.0,
            duration_ms=2,
        )
    active["voltage_mv"][0, 0] = 0.0
    result = fragment_output_diagnostics(
        SWC, [[0.5, 0, 0]], active, quiet, provenance, control, threshold_mv=-20.0, duration_ms=2
    )
    assert result["candidates"][0]["status"] == "timing_or_trace_ambiguous"
    assert result["candidates"][0]["stimulated_ticks_ms"] is None


def test_registered_outgoing_requires_complete_consistent_graph(monkeypatch):
    active, quiet, provenance, control = inputs()
    graph = SimpleNamespace(
        posts=[0], provenance={"array_sha256": {"ids.npy": "ids"}, "manifest_sha256": "graph"}
    )
    rows = [
        {"body_post": 5, "x_pre": 62, "y_pre": 0, "z_pre": 0},
        {"body_post": 8, "x_pre": 1250, "y_pre": 62, "z_pre": 0},
    ]
    page = {"total": 2, "returned": 2, "truncated": False, "pairs": rows, "source_md5": "src"}
    index = SimpleNamespace(manifest={"ids_sha256": "ids"}, query=lambda *_a, **_kw: page)
    monkeypatch.setattr(
        "service.infrastructure.stimulation.population.diagnostics.read_skeleton",
        lambda *_a, **_kw: {"swc": SWC, "sha256": provenance["morphology_sha256"]},
    )
    monkeypatch.setattr(
        "service.infrastructure.stimulation.population.diagnostics.outgoing",
        lambda *_a: {"next_offset": None, "items": [{"target_id": "5", "synapse_count": 1}]},
    )
    result = registered_outgoing_fragment_diagnostics(
        index, graph, 1, [], active, quiet, provenance, control, threshold_mv=-20.0, duration_ms=2
    )
    assert result["source_pairs"] == 2 and result["graph_pairs"] == 1
    assert [x["included_in_graph"] for x in result["candidates"]] == [True, False]
    page["truncated"] = True
    with pytest.raises(ValueError, match="Incomplete source"):
        registered_outgoing_fragment_diagnostics(
            index,
            graph,
            1,
            [],
            active,
            quiet,
            provenance,
            control,
            threshold_mv=-20.0,
            duration_ms=2,
        )
    page["truncated"] = False
    page["pairs"][0]["body_post"] = 9
    with pytest.raises(ValueError, match="counts do not match"):
        registered_outgoing_fragment_diagnostics(
            index,
            graph,
            1,
            [],
            active,
            quiet,
            provenance,
            control,
            threshold_mv=-20.0,
            duration_ms=2,
        )


def test_registered_outgoing_covers_more_than_ten_thousand_synapses(monkeypatch):
    active, quiet, provenance, control = inputs()
    count = 10001
    rows = [{"body_post": 5, "x_pre": 62, "y_pre": 0, "z_pre": 0}] * count
    graph = SimpleNamespace(
        posts=[0], provenance={"array_sha256": {"ids.npy": "ids"}, "manifest_sha256": "graph"}
    )

    def query(_body, _direction, *, limit):
        assert limit is None
        return {
            "total": count,
            "returned": count,
            "truncated": False,
            "pairs": rows,
            "source_md5": "src",
        }

    index = SimpleNamespace(manifest={"ids_sha256": "ids"}, query=query)
    monkeypatch.setattr(
        "service.infrastructure.stimulation.population.diagnostics.read_skeleton",
        lambda *_a, **_kw: {"swc": SWC, "sha256": provenance["morphology_sha256"]},
    )
    monkeypatch.setattr(
        "service.infrastructure.stimulation.population.diagnostics.outgoing",
        lambda *_a: {"next_offset": None, "items": [{"target_id": "5", "synapse_count": count}]},
    )
    monkeypatch.setattr(
        "service.infrastructure.stimulation.population.diagnostics.fragment_output_diagnostics",
        lambda *_a, **_kw: {"candidates": [{} for _ in range(count)]},
    )
    result = registered_outgoing_fragment_diagnostics(
        index, graph, 1, [], active, quiet, provenance, control, threshold_mv=-20.0, duration_ms=2
    )
    assert result["source_pairs"] == result["graph_pairs"] == count
