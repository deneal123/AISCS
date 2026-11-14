from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.edge_forced_network import (
    run_edge_forced_network,
    run_fragment_edge_network,
    run_fragment_population_network,
)
from service.infrastructure.connectome.forced_network import run_forced_network
from tests.test_forced_network import graph


def test_complete_edge_event_matches_existing_network_without_source_spike():
    reference = run_forced_network(
        graph(), seed=1, duration_ms=6, forced_cell_ids=[10], events={10: [1]}
    )
    result = run_edge_forced_network(
        graph(),
        seed=1,
        duration_ms=6,
        forced_cell_ids=[10],
        edge_events=[{"source_id": 10, "target_id": 20, "tick": 1, "count": 3000}],
    )
    np.testing.assert_array_equal(result["counts"], [0, 1, 1])
    np.testing.assert_array_equal(result["spike_neurons"], [1, 2])
    np.testing.assert_array_equal(result["spike_times_ms"], [3, 5])
    np.testing.assert_array_equal(
        result["final_voltage_relative_mv"], reference["final_voltage_relative_mv"]
    )
    np.testing.assert_array_equal(result["counts"][1:], reference["counts"][1:])


def test_absent_or_inhibitory_edges_do_not_create_source_spikes():
    for events, sign in [
        ([], 1),
        ([{"source_id": 10, "target_id": 20, "tick": 1, "count": 3000}], -1),
    ]:
        result = run_edge_forced_network(
            graph(sign), seed=1, duration_ms=6, forced_cell_ids=[10], edge_events=events
        )
        assert result["counts"].sum() == 0


@pytest.mark.parametrize(
    "event",
    [
        {"source_id": 10, "target_id": 20, "tick": 1, "count": 3001},
        {"source_id": 10, "target_id": 30, "tick": 1, "count": 1},
        {"source_id": 10, "target_id": 20, "tick": 0, "count": 1},
        {"source_id": 10, "target_id": 20, "tick": True, "count": 1},
        {"source_id": 20, "target_id": 30, "tick": 1, "count": 1},
    ],
)
def test_invalid_or_unregistered_edge_events_fail_before_simulation(event):
    with pytest.raises(ValueError):
        run_edge_forced_network(
            graph(), seed=1, duration_ms=6, forced_cell_ids=[10], edge_events=[event]
        )


def test_duplicate_edge_ticks_are_rejected():
    event = {"source_id": 10, "target_id": 20, "tick": 1, "count": 1}
    with pytest.raises(ValueError, match="Duplicate"):
        run_edge_forced_network(
            graph(), seed=1, duration_ms=6, forced_cell_ids=[10], edge_events=[event, event]
        )


def test_repeated_edge_still_checks_each_event_count():
    events = [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1},
              {'source_id': 10, 'target_id': 20, 'tick': 2, 'count': 3001}]
    with pytest.raises(ValueError, match='exceeds'):
        run_edge_forced_network(graph(), seed=1, duration_ms=6, forced_cell_ids=[10],
                                edge_events=events)


def test_sampled_response_exposes_inhibition_without_inventing_spikes():
    event = {"source_id": 10, "target_id": 20, "tick": 1, "count": 10}
    kwargs = dict(seed=1, duration_ms=6, forced_cell_ids=[10], sample_cell_ids=[20])
    active = run_edge_forced_network(graph(-1), edge_events=[event], **kwargs)
    control = run_edge_forced_network(graph(-1), edge_events=[], **kwargs)
    assert active['sampled_cell_ids'] == [20]
    np.testing.assert_array_equal(active['sampled_time_ms'], np.arange(7))
    assert active['sampled_voltage_relative_mv'].shape == (7, 1)
    assert active['counts'].sum() == 0
    assert (active['sampled_voltage_relative_mv'][3, 0]
            < control['sampled_voltage_relative_mv'][3, 0])
    np.testing.assert_array_equal(active['sampled_voltage_relative_mv'][:3],
                                  control['sampled_voltage_relative_mv'][:3])


@pytest.mark.parametrize('ids', [[], [20, 20], [True], [999]])
def test_invalid_sample_cells_rejected(ids):
    with pytest.raises(ValueError):
        run_edge_forced_network(graph(), seed=1, duration_ms=6, forced_cell_ids=[10],
                                edge_events=[], sample_cell_ids=ids)


def test_short_recording_supports_more_than_4096_targets():
    count = 5000
    model = SimpleNamespace(size=count + 1, ids=np.arange(1, count + 2, dtype=np.int64),
        ptr=np.r_[0, np.full(count + 1, count, dtype=np.int64)],
        posts=np.arange(1, count + 1, dtype=np.int32),
        counts=np.ones(count, dtype=np.int32), signs=np.ones(count + 1, dtype=np.int8),
        provenance={'manifest_sha256': 'a' * 64})
    targets = list(range(2, count + 2))
    result = run_edge_forced_network(model, seed=1, duration_ms=1, forced_cell_ids=[1],
                                     edge_events=[], sample_cell_ids=targets)
    assert result['sampled_voltage_relative_mv'].shape == (2, count)
    assert result['sampled_cell_ids'] == targets


def test_fragment_wrapper_requires_matching_graph_and_keeps_source_silent():
    model = graph()
    model.provenance["manifest_sha256"] = "a" * 64
    row = {
        "included_in_graph": True,
        "partner_id": "20",
        "centerline_distance_um": 0.1,
        "status": "stimulus_only_crossing",
        "stimulated_ticks_ms": [1],
        "control_ticks_ms": [],
    }
    diagnostics = {
        "body_id": "10",
        "graph_sha256": "a" * 64,
        "simulation_sha256": "c" * 64,
        "threshold_mv": -20.0,
        "candidates": [row],
        "source_pairs": 1,
        "duration_ms": 6,
        "graph_pairs": 1,
    }
    result = run_fragment_edge_network(
        model, diagnostics, seed=1, duration_ms=6, max_distance_um=0.2
    )
    assert result["network"]["counts"][0] == 0
    assert result["schedule"]["edge_events"] == [
        {"source_id": 10, "target_id": 20, "tick": 1, "count": 1}
    ]
    with pytest.raises(ValueError, match="identity"):
        run_fragment_edge_network(
            model,
            {**diagnostics, "graph_sha256": "b" * 64},
            seed=1,
            duration_ms=6,
            max_distance_um=0.2,
        )


def test_population_sources_are_silenced_and_require_identical_stimulation():
    model = graph()
    model.provenance["manifest_sha256"] = "a" * 64

    def diagnostic(source, target):
        return {
            "body_id": str(source),
            "graph_sha256": "a" * 64,
            "simulation_sha256": "c" * 64,
            "threshold_mv": -20.0,
            "duration_ms": 6,
            "source_pairs": 1,
            "graph_pairs": 1,
            "candidates": [
                {
                    "included_in_graph": True,
                    "partner_id": str(target),
                    "centerline_distance_um": 0.1,
                    "status": "stimulus_only_crossing",
                    "stimulated_ticks_ms": [1],
                    "control_ticks_ms": [],
                }
            ],
        }

    first, second = diagnostic(10, 20), diagnostic(20, 30)
    result = run_fragment_population_network(
        model, [first, second], seed=1, duration_ms=6, max_distance_um=0.2
    )
    assert result["source_ids"] == [10, 20]
    assert result["network"]["counts"][0] == result["network"]["counts"][1] == 0
    assert len(result["schedules"]) == 2
    with pytest.raises(ValueError, match="Duplicate"):
        run_fragment_population_network(
            model, [first, first], seed=1, duration_ms=6, max_distance_um=0.2
        )
    with pytest.raises(ValueError, match="different stimulation"):
        run_fragment_population_network(
            model,
            [first, {**second, "simulation_sha256": "d" * 64}],
            seed=1,
            duration_ms=6,
            max_distance_um=0.2,
        )


def test_population_capture_is_paired_and_reports_no_targets():
    model = graph(-1)
    model.provenance['manifest_sha256'] = 'a' * 64
    base = {'body_id': '10', 'graph_sha256': 'a' * 64, 'simulation_sha256': 'c' * 64,
            'threshold_mv': -20.0, 'duration_ms': 6, 'source_pairs': 1, 'graph_pairs': 1}
    row = {'included_in_graph': True, 'partner_id': '20', 'centerline_distance_um': 0.1,
           'status': 'stimulus_only_crossing', 'stimulated_ticks_ms': [1], 'control_ticks_ms': []}
    result = run_fragment_population_network(
        model, [{**base, 'candidates': [row]}], seed=1, duration_ms=6,
        max_distance_um=0.2, capture_target_response=True,
    )['target_response']
    assert result['status'] == 'recorded' and result['target_ids'] == [20]
    assert result['delta_relative_mv'].shape == (7, 1)
    assert result['delta_relative_mv'].min() < 0
    assert result['delta_relative_mv'][0, 0] == 0
    row = {**row, 'status': 'no_crossing', 'stimulated_ticks_ms': []}
    empty = run_fragment_population_network(
        model, [{**base, 'candidates': [row]}], seed=1, duration_ms=6,
        max_distance_um=0.2, capture_target_response=True,
    )['target_response']
    assert empty == {'status': 'no_direct_targets', 'target_count': 0}


def test_network_response_captures_downstream_cells_without_claiming_physiology(monkeypatch):
    model = graph()
    model.provenance['manifest_sha256'] = 'a' * 64
    schedule = {'source_id': 10, 'graph_sha256': 'a' * 64, 'simulation_sha256': 'c' * 64,
                'threshold_mv': -20.0, 'edge_events': [
                    {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 3000}]}
    monkeypatch.setattr('service.infrastructure.stimulation.population.diagnostics.'
                        'fragment_edge_schedule', lambda *args, **kwargs: schedule)
    result = run_fragment_population_network(
        model, [{}], seed=1, duration_ms=6, max_distance_um=0.2,
        capture_target_response=True, response_scope='network',
    )
    response = result['target_response']
    assert response['scope'] == 'network-excluding-forced-sources'
    assert response['target_ids'] == [20, 30]
    np.testing.assert_array_equal(result['network']['counts'], [0, 1, 1])
    assert np.any(response['delta_relative_mv'][:, 1] != 0)
    assert np.all(np.isfinite(response['delta_relative_mv']))


def test_network_snapshots_use_explicit_bounded_times(monkeypatch):
    monkeypatch.setattr('service.domain.target_response_limits.MAX_TARGET_RESPONSE_VALUES', 10)
    model = graph()
    model.provenance['manifest_sha256'] = 'a' * 64
    schedule = {'source_id': 10, 'graph_sha256': 'a' * 64, 'simulation_sha256': 'c' * 64,
                'threshold_mv': -20.0, 'edge_events': [
                    {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 3000}]}
    monkeypatch.setattr('service.infrastructure.stimulation.population.diagnostics.'
                        'fragment_edge_schedule', lambda *args, **kwargs: schedule)
    result = run_fragment_population_network(
        model, [{}], seed=1, duration_ms=6, max_distance_um=0.2,
        capture_target_response=True, response_scope='network',
    )['target_response']
    np.testing.assert_array_equal(result['time_ms'], [0, 2, 4, 6])
    assert result['active_relative_mv'].shape == (4, 2)


def test_sparse_delta_reproduces_all_cells_at_each_tick_against_separate_control():
    model = graph()
    events = [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 3000}]
    args = dict(seed=1, duration_ms=6, forced_cell_ids=[10], sample_cell_ids=[10, 20, 30])
    active = run_edge_forced_network(model, edge_events=events, capture_sparse_delta=True, **args)
    quiet = run_edge_forced_network(model, edge_events=[], **args)
    sparse = active['sparse_delta']
    assert sparse['status'] == 'recorded' and len(sparse['offsets']) == 8
    dense = np.zeros((7, 3), dtype=np.float32)
    for tick in range(7):
        start, end = sparse['offsets'][tick:tick + 2]
        dense[tick, sparse['indices'][start:end]] = sparse['values'][start:end]
    np.testing.assert_array_equal(dense, active['sampled_voltage_relative_mv']
                                  - quiet['sampled_voltage_relative_mv'])
    np.testing.assert_array_equal(active['spike_times_ms'], [3, 5])


def test_sparse_delta_limit_does_not_publish_partial_values(monkeypatch):
    monkeypatch.setattr('service.domain.target_response_limits.MAX_TARGET_RESPONSE_VALUES', 1)
    result = run_edge_forced_network(
        graph(), seed=1, duration_ms=6, forced_cell_ids=[10], capture_sparse_delta=True,
        edge_events=[{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 3000}],
    )
    assert result['sparse_delta'] == {'status': 'limit_exceeded'}
