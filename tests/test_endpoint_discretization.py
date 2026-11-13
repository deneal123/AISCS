from copy import deepcopy

import pytest

from service.infrastructure.stimulation.feedback.endpoint_discretization import (
    audit_effective_positions,
    choose_endpoint_resolutions,
    discretize_endpoints,
    prepare_discretized_events,
    validate_prepared_events,
)


def test_effective_position_audits_interior_events_after_remeshing():
    events = [{'child_node_id': 4, 'position': .6}, {'child_node_id': 4, 'position': 1.}]
    edge = {4: [[0, 0, 0], [10, 0, 0]]}
    observations = [[6, 1, 0], [10, 0, 0]]
    coarse = audit_effective_positions(events, edge, observations, {4: 1})
    fine = audit_effective_positions(events, edge, observations, {4: 5})
    assert coarse[0]['effective_position'] == .5
    assert fine[0]['effective_position'] == .7
    assert fine[0]['requires_endpoint_relocation'] is False
    assert fine[0]['observation_distance_um'] == pytest.approx(2 ** .5)
    assert fine[1]['effective_position'] == .9
    assert fine[1]['requires_endpoint_relocation'] is True
    assert fine[1]['shift_um'] == pytest.approx(1.)


@pytest.mark.parametrize('resolution', [0, 2, True, -1])
def test_effective_position_rejects_invalid_resolution(resolution):
    with pytest.raises(ValueError, match='resolution'):
        audit_effective_positions([{'child_node_id': 4, 'position': .5}],
                                  {4: [[0, 0, 0], [1, 0, 0]]}, [[.5, 0, 0]],
                                  {4: resolution})


def test_explicit_edge_mapping_reports_shift_without_mutating_events():
    events = [{'child_node_id': 4, 'position': 0., 'time_ms': 1},
              {'child_node_id': 4, 'position': 1., 'time_ms': 2},
              {'child_node_id': 4, 'position': .8, 'time_ms': 3}]
    original = deepcopy(events)
    mapped, evidence = discretize_endpoints(events, {4: [[0, 0, 0], [6, 0, 0]]},
                                            nseg_per_edge=3, max_shift_um=1.)
    assert events == original
    assert [row['position'] for row in mapped] == pytest.approx([1/6, 5/6, .8])
    assert [row['shift_um'] for row in evidence] == pytest.approx([1., 1.])
    assert [row['event_index'] for row in evidence] == [0, 1]
    assert [row['original_position'] for row in evidence] == [0., 1.]


def test_adaptive_resolution_satisfies_both_endpoint_observations():
    events = [{'child_node_id': 4, 'position': 0.}, {'child_node_id': 4, 'position': 1.}]
    original = deepcopy(events)
    result = choose_endpoint_resolutions(events, {4: [[0, 0, 0], [6, 0, 0]]},
        [[0, 0, 0], [6, 1.9, 0]], max_shift_um=2., max_observation_distance_um=2., max_nseg=9)
    assert result[4]['nseg'] == 5
    assert result[4]['max_observation_distance_um'] == pytest.approx(3.97**.5)
    assert events == original


def test_adaptive_resolution_checks_interior_events_on_remeshed_edge():
    events = [{'child_node_id': 4, 'position': 1.}, {'child_node_id': 4, 'position': .5}]
    result = choose_endpoint_resolutions(events, {4: [[0, 0, 0], [6, 0, 0]]},
        [[6, 0, 0], [3, 0, 0]], max_shift_um=1., max_observation_distance_um=2., max_nseg=5)
    assert result[4]['nseg'] == 3
    with pytest.raises(ValueError, match='No endpoint resolution'):
        choose_endpoint_resolutions(events, {4: [[0, 0, 0], [6, 0, 0]]},
            [[6, 0, 0], [3, 3, 0]], max_shift_um=1., max_observation_distance_um=2., max_nseg=5)


def test_prepared_replay_is_bounded_and_preserves_original_positions():
    events = [{'child_node_id': 4, 'position': 1., 'time_ms': 1.},
              {'child_node_id': 4, 'position': .5, 'time_ms': 2.}]
    original = deepcopy(events)
    result = prepare_discretized_events(events, {4: [[0, 0, 0], [6, 0, 0]]},
        [[6, 0, 0], [3, 0, 0]], max_shift_um=1., max_observation_distance_um=2., max_nseg=5)
    assert events == original
    assert result['nseg_by_edge'] == {'4': 3}
    assert result['effective_events'][0]['position'] == pytest.approx(5/6)
    assert result['effective_events'][1] == events[1]
    assert len(result['sha256']) == 64
    assert result['evidence'][0]['observation_distance_um'] == pytest.approx(1.)


def test_prepared_replay_rejects_out_of_bounds_interior_only_edge():
    events = [{'child_node_id': 4, 'position': .5}]
    with pytest.raises(ValueError, match='Effective event exceeds'):
        prepare_discretized_events(events, {4: [[0, 0, 0], [6, 0, 0]]}, [[3, 3, 0]],
            max_shift_um=1., max_observation_distance_um=2., max_nseg=5)


def test_prepared_replay_recomputes_from_verified_inputs_and_is_snapshot():
    events = [{'child_node_id': 4, 'position': 1., 'time_ms': 1.}]
    edges = {4: [[0, 0, 0], [6, 0, 0]]}
    observations = [[6, 0, 0]]
    limits = {'max_shift_um': 1., 'max_observation_distance_um': 2., 'max_nseg': 5}
    prepared = prepare_discretized_events(events, edges, observations, **limits)
    assert validate_prepared_events(prepared, events, edges, observations, **limits) == prepared
    events[0]['time_ms'] = 2.
    assert prepared['original_events'][0]['time_ms'] == 1.
    with pytest.raises(ValueError, match='does not match verified inputs'):
        validate_prepared_events(prepared, events, edges, observations, **limits)
    altered = deepcopy(prepared)
    altered['effective_events'][0]['position'] = .5
    with pytest.raises(ValueError, match='does not match verified inputs'):
        validate_prepared_events(altered, prepared['original_events'], edges, observations,
                                 **limits)


@pytest.mark.parametrize('limit', [0., .999])
def test_refuses_entire_batch_if_explicit_bound_is_exceeded(limit):
    events = [{'child_node_id': 4, 'position': 0.}, {'child_node_id': 4, 'position': 1.}]
    before = deepcopy(events)
    with pytest.raises(ValueError, match='exceeds explicit displacement'):
        discretize_endpoints(events, {4: [[0, 0, 0], [6, 0, 0]]},
                             nseg_per_edge=3, max_shift_um=limit)
    assert events == before


def test_observation_distance_is_checked_independently_of_endpoint_shift():
    event = {'child_node_id': 4, 'position': 1.}
    geometry = {4: [[0, 0, 0], [6, 0, 0]]}
    with pytest.raises(ValueError, match='observation distance limit'):
        discretize_endpoints([event], geometry, nseg_per_edge=3, max_shift_um=1.,
                             observations_um=[[6, 2, 0]], max_observation_distance_um=2.)
    _, evidence = discretize_endpoints([event], geometry, nseg_per_edge=3, max_shift_um=1.,
                                       observations_um=[[6, 2, 0]],
                                       max_observation_distance_um=3.)
    assert evidence[0]['observation_distance_um'] == pytest.approx(5**.5)
    assert evidence[0]['observation_um'] == [6., 2., 0.]


def test_requires_observations_and_their_limit_together():
    with pytest.raises(ValueError, match='supplied together'):
        discretize_endpoints([], {}, nseg_per_edge=1, max_shift_um=1., observations_um=[])


@pytest.mark.parametrize('geometry', [None, [[0, 0, 0], [0, 0, 0]],
                                       [[0, 0, 0], [float('nan'), 0, 0]]])
def test_rejects_missing_degenerate_or_nonfinite_edge_geometry(geometry):
    with pytest.raises(ValueError):
        discretize_endpoints([{'child_node_id': 4, 'position': 1.}], {4: geometry},
                             nseg_per_edge=1, max_shift_um=10.)


@pytest.mark.parametrize('nseg,limit', [(2, 1.), (0, 1.), (True, 1.), (1, float('nan')), (1, -1.)])
def test_rejects_invalid_precision_settings(nseg, limit):
    with pytest.raises(ValueError):
        discretize_endpoints([], {}, nseg_per_edge=nseg, max_shift_um=limit)
