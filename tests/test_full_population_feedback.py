import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.feedback.full_population import run_full_population_feedback


def test_timeline_preserves_extrema_and_grid_endpoints():
    from service.application.feedback.full_population import _timeline

    time = np.arange(10001) * .05
    active, control, stimulus = (np.zeros_like(time) for _ in range(3))
    active[50], control[65], stimulus[80] = 4., -3., 1.
    timeline = _timeline(time, active, control, stimulus)
    assert timeline['time_ms'][0] == 0. and timeline['time_ms'][-1] == time[-1]
    assert max(timeline['neural_uv']) == 4. and min(timeline['control_uv']) == -3.
    assert max(timeline['stimulus_fraction']) == 1.
    assert timeline['shown_samples'] <= 3200


def test_geometry_runner_shares_scratch_and_removes_it_on_failure(tmp_path, monkeypatch):
    from service.application.feedback.full_population import run_full_population_from_geometry

    calls = []

    def fake_diagnostics(cell, graph, index, **options):
        calls.append(cell['id'])
        return {'body_id': str(cell['id']), 'morphology_sha256': cell['morphology_sha256'],
                'candidates': [], 'graph_sha256': 'a' * 64, 'source_md5': 'd' * 32,
                'simulation_sha256': 'e' * 64, 'threshold_mv': -20., 'duration_ms': 10}

    def fake_run(*_args, metadata_factory, diagnostics_factory, **_kwargs):
        cells = [{'id': 10, 'morphology_sha256': 'b' * 64}]
        first = metadata_factory(cells)
        assert metadata_factory(cells) == first
        assert diagnostics_factory((10,)) == first['diagnostics']
        raise RuntimeError('solver failed')

    monkeypatch.setattr('service.infrastructure.stimulation.population.source_store.'
                        'source_geometry_diagnostics', fake_diagnostics)
    monkeypatch.setattr('service.application.feedback.full_population.run_full_population_feedback',
                        fake_run)
    with pytest.raises(RuntimeError, match='solver failed'):
        run_full_population_from_geometry({}, [], None, graph=SimpleNamespace(provenance={
            'manifest_sha256': 'a' * 64, 'array_sha256': {'ids.npy': 'c' * 64}}),
            index=SimpleNamespace(manifest={'source_md5': 'd' * 32, 'ids_sha256': 'c' * 64}),
            morphology_sha256={10: 'b' * 64}, configuration_sha256='e' * 64,
            output_directory=tmp_path / 'result',
            replay_options={'threshold_mv': -20., 'duration_ms': 10}, max_source_distance_um=2.)
    assert calls == [10]
    assert list(tmp_path.iterdir()) == []


def test_unresolved_source_reports_identity_and_prevents_replay(tmp_path, monkeypatch):
    from service.application.feedback.full_population import run_full_population_from_geometry

    def diagnostics(cell, graph, index, **options):
        return {'body_id': str(cell['id']), 'morphology_sha256': cell['morphology_sha256'],
                'candidates': [{'included_in_graph': True, 'status': 'geometry_unresolved'}],
                'graph_sha256': 'a' * 64, 'source_md5': 'd' * 32,
                'simulation_sha256': 'e' * 64, 'threshold_mv': -20., 'duration_ms': 10}

    def run(*_args, metadata_factory, **_kwargs):
        metadata_factory([{'id': 10, 'morphology_sha256': 'b' * 64}])
        pytest.fail('unresolved geometry must stop the replay')

    monkeypatch.setattr('service.infrastructure.stimulation.population.source_store.'
                        'source_geometry_diagnostics', diagnostics)
    monkeypatch.setattr('service.application.feedback.full_population.run_full_population_feedback',
                        run)
    with pytest.raises(ValueError, match='cell 10, 1 of 1 synapses exceed 2 um'):
        run_full_population_from_geometry({}, [], None, graph=SimpleNamespace(provenance={
            'manifest_sha256': 'a' * 64, 'array_sha256': {'ids.npy': 'c' * 64}}),
            index=SimpleNamespace(manifest={'source_md5': 'd' * 32, 'ids_sha256': 'c' * 64}),
            morphology_sha256={10: 'b' * 64}, configuration_sha256='e' * 64,
            output_directory=tmp_path / 'result',
            replay_options={'threshold_mv': -20., 'duration_ms': 10}, max_source_distance_um=2.)
    assert list(tmp_path.iterdir()) == []


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _arguments(tmp_path):
    ids = [10, 20]
    return dict(metadata={'graph_sha256': 'a' * 64}, stimulus=[0., 1., 0.], rate_table=[],
        graph=SimpleNamespace(ids=np.array(ids), provenance={'manifest_sha256': 'a' * 64}),
        source_ids=ids, morphology_sha256={10: 'b' * 64, 20: 'c' * 64},
        baseline_schedule={'placeholder': True}, baseline_sha256='d' * 64,
        configuration_sha256='e' * 64, metadata_factory=lambda cells: {},
        diagnostics_factory=lambda ids: {}, index=None, directories=[], synapse_parameters={},
        replay_options={'expected_ids': ids, 'time_ms': [0., .05, .1], 'duration_ms': .1},
        max_iterations=2, max_events=10, max_source_distance_um=2., max_target_distance_um=2.,
        output_directory=tmp_path / 'published')


def test_paired_full_population_publishes_only_after_convergence(tmp_path, monkeypatch):
    calls = []
    def initial(metadata, stimulus, rate_table, *, event_path, **kwargs):
        calls.append(np.asarray(stimulus).copy())
        event_path.write_text('active' if np.any(stimulus) else 'control', encoding='utf8')
        return {'event_sha256': _digest(event_path), 'neural_uv': np.asarray(stimulus), 'cells': 2}

    def iterate(metadata, stimulus, rate_table, *, active_path, active_sha256, control_path,
                control_sha256, output_event_path, **kwargs):
        assert active_sha256 == _digest(active_path) and control_sha256 == _digest(control_path)
        assert kwargs['baseline_schedule'] == {'placeholder': True}
        output_event_path.write_text('converged', encoding='utf8')
        return {'status': 'converged', 'iterations': 2, 'feedback_schedule_sha256': 'f' * 64,
                'replay': {'event_sha256': _digest(output_event_path),
                           'neural_uv': [0., 2., 0.] if np.any(stimulus) else [0., 0., 0.],
                           'cells': 2}}

    monkeypatch.setattr('service.application.feedback.full_population.'
                        'replay_verified_feedback_to_archive', initial)
    monkeypatch.setattr('service.application.feedback.full_population.iterate_archived_feedback',
                        iterate)
    args = _arguments(tmp_path)
    result = run_full_population_feedback(**args)
    np.testing.assert_array_equal(calls[0], [0., 1., 0.])
    np.testing.assert_array_equal(calls[1], [0., 0., 0.])
    destination = args['output_directory']
    manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf8'))
    assert result['status'] == 'converged' and result['manifest_sha256'] == _digest(
        destination / 'manifest.json')
    assert manifest['cells'] == 2 and 'not biological validation' in manifest['interpretation']
    assert all(_digest(destination / name) == digest
               for name, digest in manifest['file_hashes'].items())
    with np.load(destination / 'signals.npz') as signals:
        np.testing.assert_array_equal(signals['control_uv'], [0., 0., 0.])
        np.testing.assert_array_equal(signals['converged_active_uv'], [0., 2., 0.])
    assert sorted(path.name for path in tmp_path.iterdir()) == ['published']


@pytest.mark.parametrize('outcome', ['iteration_limit', 'cycle_detected', 'exception'])
def test_nonconverged_or_failed_run_never_publishes(tmp_path, monkeypatch, outcome):
    def initial(metadata, stimulus, rate_table, *, event_path, **kwargs):
        event_path.write_text('staged', encoding='utf8')
        return {'event_sha256': _digest(event_path), 'neural_uv': stimulus, 'cells': 2}
    def iterate(*args, **kwargs):
        if outcome == 'exception':
            raise RuntimeError('failed')
        return {'status': outcome, 'iterations': 2}
    monkeypatch.setattr('service.application.feedback.full_population.'
                        'replay_verified_feedback_to_archive', initial)
    monkeypatch.setattr('service.application.feedback.full_population.iterate_archived_feedback',
                        iterate)
    args = _arguments(tmp_path)
    if outcome == 'exception':
        with pytest.raises(RuntimeError, match='failed'):
            run_full_population_feedback(**args)
    else:
        assert run_full_population_feedback(**args)['status'] == outcome
    assert list(tmp_path.iterdir()) == []


def test_active_network_failure_after_control_converges_does_not_publish(tmp_path, monkeypatch):
    stages = []

    def initial(metadata, stimulus, rate_table, *, event_path, **kwargs):
        event_path.write_text('staged', encoding='utf8')
        return {'event_sha256': _digest(event_path), 'neural_uv': stimulus, 'cells': 2}

    def iterate(metadata, stimulus, rate_table, *, output_event_path, **kwargs):
        stages.append('active' if np.any(stimulus) else 'control')
        if np.any(stimulus):
            return {'status': 'iteration_limit', 'iterations': 2}
        output_event_path.write_text('control converged', encoding='utf8')
        return {'status': 'converged', 'iterations': 1, 'feedback_schedule_sha256': 'f' * 64,
                'replay': {'event_sha256': _digest(output_event_path),
                           'neural_uv': [0., 0., 0.], 'cells': 2}}

    monkeypatch.setattr('service.application.feedback.full_population.'
                        'replay_verified_feedback_to_archive', initial)
    monkeypatch.setattr('service.application.feedback.full_population.iterate_archived_feedback',
                        iterate)
    result = run_full_population_feedback(**_arguments(tmp_path))
    assert result == {'status': 'iteration_limit', 'iterations': 2}
    assert stages == ['control', 'active']
    assert list(tmp_path.iterdir()) == []


def test_subset_and_existing_destination_are_rejected(tmp_path):
    args = _arguments(tmp_path)
    with pytest.raises(ValueError, match='identity'):
        run_full_population_feedback(**{**args, 'source_ids': [10]})
    args['output_directory'].mkdir()
    with pytest.raises(ValueError, match='new directory'):
        run_full_population_feedback(**args)


def test_bad_archive_digest_never_reaches_network_or_publishes(tmp_path, monkeypatch):
    def initial(metadata, stimulus, rate_table, *, event_path, **kwargs):
        event_path.write_text('corrupted', encoding='utf8')
        return {'event_sha256': '0' * 64, 'neural_uv': stimulus, 'cells': 2}
    monkeypatch.setattr('service.application.feedback.full_population.'
                        'replay_verified_feedback_to_archive', initial)
    monkeypatch.setattr('service.application.feedback.full_population.iterate_archived_feedback',
                        lambda *args, **kwargs: pytest.fail('must not enter network'))
    with pytest.raises(ValueError, match='archive digest'):
        run_full_population_feedback(**_arguments(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_empty_network_runs_real_archive_and_convergence_path(tmp_path, monkeypatch):
    from service.application.feedback.fixed_inputs import fixed_input_digest

    ids = [10, 20]
    hashes = {10: 'b' * 64, 20: 'c' * 64}
    proof = {body: {'body_id': str(body), 'morphology_sha256': hashes[body]} for body in ids}
    diagnostics = {body: {'body_id': str(body), 'morphology_sha256': hashes[body],
        'graph_sha256': 'a' * 64, 'threshold_mv': -20., 'duration_ms': 1,
        'candidates': []} for body in ids}
    geometry = {'edge_node_ids': np.array([7]), 'starts_um': np.array([[0., 0., 0.]]),
                'ends_um': np.array([[2., 0., 0.]]), 'midpoints_um': np.array([[1., 0., 0.]]),
                'endpoint_radii_um': np.array([[.1, .1]])}
    cells = [{'id': body, 'morphology_sha256': hashes[body], 'geometry': geometry} for body in ids]
    source_rows = {body: [] for body in ids}
    provenance_hash = hashlib.sha256(json.dumps({str(body): [] for body in ids}, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    baseline = {'graph_sha256': 'a' * 64, 'source_ids': ids,
        'target_morphology_sha256': {}, 'events_by_target': source_rows,
        'provenance_by_target': {body: [] for body in ids}, 'provenance_sha256': provenance_hash,
        'event_count': 0, 'outside_window': 0, 'unresolved': []}

    def solve(metadata, stimulus, table, *, event_factory, device_window_factory, **kwargs):
        assert event_factory(tuple(ids)) == source_rows
        device = device_window_factory(cells)
        assert device['selected_indices'] == {10: [], 20: []}
        device['sink'](0, 21, [{'id': body, 'neural_uv': np.zeros(21),
                                'selected_voltage_mv': np.empty((0, 21))} for body in ids])
        yield ids, {'table_clamped_cell_ids': []}

    monkeypatch.setattr(
        'service.application.feedback.population_bulk_replay.solve_population', solve,
    )
    graph = SimpleNamespace(ids=np.array(ids), ptr=np.array([0, 0, 0]), posts=np.array([], int),
                            signs=np.array([1, 1]), provenance={'manifest_sha256': 'a' * 64})
    args = _arguments(tmp_path)
    args.update(stimulus=np.zeros(21), graph=graph, morphology_sha256=hashes,
        baseline_schedule=baseline, baseline_sha256=fixed_input_digest(baseline),
        metadata_factory=lambda cells: {'provenance': proof, 'diagnostics': diagnostics},
        diagnostics_factory=lambda batch: {body: diagnostics[body] for body in batch},
        replay_options={'expected_ids': ids, 'audited_sources': {}, 'params': None,
            'time_ms': np.arange(21) * .05, 'threshold_mv': -20., 'duration_ms': 1,
            'electrode_um': [10., 0., 0.], 'reference_um': [20., 0., 0.],
            'conductivity_s_m': .3, 'clearance_um': 1., 'segment_budget': 10,
            'output_budget_bytes': 10000})
    result = run_full_population_feedback(**args)
    assert result['status'] == 'converged' and result['iterations'] == 1
    manifest = json.loads((args['output_directory'] / 'manifest.json').read_text(encoding='utf8'))
    assert manifest['cells'] == 2


def test_connected_pair_replays_feedback_until_schedule_converges(tmp_path, monkeypatch):
    from service.application.feedback.fixed_inputs import fixed_input_digest

    ids = [10, 20]
    hashes = {10: 'b' * 64, 20: 'c' * 64}
    graph = SimpleNamespace(ids=np.array(ids), ptr=np.array([0, 1, 1]),
        posts=np.array([1]), counts=np.array([1]), signs=np.array([1, 1]),
        provenance={'manifest_sha256': 'a' * 64})
    geometry = {'edge_node_ids': np.array([7]), 'starts_um': np.array([[0., 0., 0.]]),
        'ends_um': np.array([[2., 0., 0.]]), 'midpoints_um': np.array([[1., 0., 0.]]),
        'endpoint_radii_um': np.array([[.1, .1]])}
    cells = [{'id': body, 'morphology_sha256': hashes[body], 'geometry': geometry}
             for body in ids]
    proof = {body: {'body_id': str(body), 'morphology_sha256': hashes[body]} for body in ids}
    diagnostics = {body: {'body_id': str(body), 'morphology_sha256': hashes[body],
        'graph_sha256': 'a' * 64, 'simulation_sha256': 'e' * 64, 'source_md5': 'verified',
        'threshold_mv': -20., 'duration_ms': 5, 'source_pairs': 0, 'graph_pairs': 0,
        'candidates': []} for body in ids}
    diagnostics[10].update(source_pairs=1, graph_pairs=1, candidates=[{
        'included_in_graph': True, 'partner_id': '20', 'source_position_8nm': [1, 2, 3],
        'child_node_id': 7, 'segment_fraction': .5, 'result_segment_index': 0,
        'centerline_distance_um': .1, 'status': 'no_crossing',
        'stimulated_ticks_ms': [], 'control_ticks_ms': []}])
    pair = {'body_pre': 10, 'body_post': 20, 'x_pre': 1, 'y_pre': 2, 'z_pre': 3,
            'x_post': 4, 'y_post': 5, 'z_post': 6}
    index = SimpleNamespace(query=lambda *_a, **_k: {'pairs': [pair], 'truncated': False,
        'source_md5': 'verified', 'total': 1, 'returned': 1})
    mapping = 'service.infrastructure.stimulation.population.pair_mapping.'
    monkeypatch.setattr(mapping + 'outgoing', lambda *_a: {'next_offset': None,
        'items': [{'target_id': '20', 'synapse_count': 1}]})
    monkeypatch.setattr(mapping + 'read_skeleton', lambda *_a: {'swc': 'verified',
        'sha256': hashes[20], 'body_id': '20'})
    monkeypatch.setattr(mapping + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9], 'segment_fractions': [.5], 'centerline_distances_um': [.1]})
    empty = {body: [] for body in ids}
    proof_hash = hashlib.sha256(json.dumps({str(body): [] for body in ids}, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    baseline = {'graph_sha256': 'a' * 64, 'source_ids': ids, 'target_morphology_sha256': {},
        'events_by_target': empty, 'provenance_by_target': empty, 'provenance_sha256': proof_hash,
        'event_count': 0, 'outside_window': 0, 'unresolved': []}
    delivered = []

    def solve(_metadata, stimulus, _table, *, event_factory, device_window_factory, **_kwargs):
        events = event_factory(tuple(ids))
        delivered.append(len(events[20]))
        device = device_window_factory(cells)
        trace = np.full(101, -65.)
        trace[10] = -10.  # Common control event must propagate in both networks.
        if np.any(stimulus):
            trace[40] = -10.  # Additional event belongs only to the stimulated network.
        device['sink'](0, 101, [
            {'id': 10, 'neural_uv': np.zeros(101), 'selected_voltage_mv': [trace]},
            {'id': 20, 'neural_uv': np.full(101, len(events[20])),
             'selected_voltage_mv': np.empty((0, 101))}])
        yield ids, {'table_clamped_cell_ids': []}

    monkeypatch.setattr(
        'service.application.feedback.population_bulk_replay.solve_population', solve,
    )
    args = _arguments(tmp_path)
    args.update(stimulus=np.ones(101), graph=graph, index=index, morphology_sha256=hashes,
        baseline_schedule=baseline, baseline_sha256=fixed_input_digest(baseline),
        metadata_factory=lambda cells: {'provenance': proof, 'diagnostics': diagnostics},
        diagnostics_factory=lambda batch: {body: diagnostics[body] for body in batch},
        synapse_parameters={1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2.,
                                'reversal_mv': 0.}},
        replay_options={'expected_ids': ids, 'audited_sources': {}, 'params': None,
            'time_ms': np.arange(101) * .05, 'threshold_mv': -20., 'duration_ms': 5,
            'electrode_um': [10., 0., 0.], 'reference_um': [20., 0., 0.],
            'conductivity_s_m': .3, 'clearance_um': 1., 'segment_budget': 10,
            'output_budget_bytes': 10000})
    progress = []
    result = run_full_population_feedback(**args, export_markers=True, progress=progress.append)
    assert result['status'] == 'converged'
    assert delivered == [0, 0, 1, 2]
    assert progress == [
        {'phase': 'full_active', 'done': 0, 'total': 2},
        {'phase': 'full_active', 'done': 2, 'total': 2},
        {'phase': 'full_control', 'done': 0, 'total': 2},
        {'phase': 'full_control', 'done': 2, 'total': 2},
        {'phase': 'full_control_feedback', 'iteration': 1, 'done': 0, 'total': 2},
        {'phase': 'full_control_feedback', 'iteration': 1, 'done': 2, 'total': 2},
        {'phase': 'full_control_feedback', 'iteration': 2, 'done': 0, 'total': 2},
        {'phase': 'full_feedback', 'iteration': 1, 'done': 0, 'total': 2},
        {'phase': 'full_feedback', 'iteration': 1, 'done': 2, 'total': 2},
        {'phase': 'full_feedback', 'iteration': 2, 'done': 0, 'total': 2},
    ]
    with np.load(args['output_directory'] / 'signals.npz') as data:
        assert np.all(data['converged_active_uv'] == 2.)
        assert np.all(data['control_uv'] == 1.)
    preview = json.loads((args['output_directory'] / 'preview.json').read_text(encoding='utf8'))
    assert preview['candidate_cell_time_markers'] == 2
    manifest = json.loads((args['output_directory'] / 'manifest.json').read_text(encoding='utf8'))
    marker = next(item for item in manifest['files']
                  if item['name'] == 'coupled-source-events.bin')
    assert marker['sha256'] == _digest(args['output_directory'] / marker['name'])
