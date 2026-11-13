import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.feedback.loop import iterate_population_feedback
from service.application.feedback.validation import validate_population_feedback
from tests.test_forced_network import graph
from tests.test_fragment_population_contract import example


def test_partial_source_geometry_is_not_misrepresented_as_coupled_feedback(monkeypatch):
    metadata = {'configuration': {**example(), 'allow_partial_geometry': True},
                'schedules': [{'edge_events': [], 'unresolved_geometry': [{'candidate_index': 0}]}]}
    monkeypatch.setattr('service.application.feedback.loop.load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    with pytest.raises(ValueError, match='Partial source geometry'):
        iterate_population_feedback('archive', graph(), SimpleNamespace(), [], parameters={},
                                    max_iterations=3, allow_partial_geometry=False)


def test_partial_source_convergence_remains_explicit_and_omits_unknown_events(monkeypatch):
    config = {**example(), 'allow_partial_geometry': True}
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    unresolved = {'included_in_graph': True, 'partner_id': '30', 'source_position_8nm': [1, 2, 3],
                  'stimulated_ticks_ms': None, 'status': 'geometry_unresolved',
                  'centerline_distance_um': 2.1}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': '10', 'morphology_sha256': 'b' * 64, 'candidates': [unresolved]},
        {'body_id': '20', 'morphology_sha256': 'b' * 64, 'candidates': []}],
        'schedules': [{'edge_events': [], 'unresolved_geometry': [{'candidate_index': 0}]},
                      {'edge_events': [], 'unresolved_geometry': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata, 'manifest': {'fake': 'source'}})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    def output(*_args, **kwargs):
        assert kwargs['max_source_distance_um'] == 2
        return {'edge_events': [], 'candidates': []}
    monkeypatch.setattr(module + 'feedback_output_events', output)
    def replay(config, _directories, _schedule, _hashes, *, omitted_pairs, solution_sink):
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
        parameters={}, max_iterations=3, allow_partial_geometry=True)
    assert result['status'] == 'converged_partial'
    assert result['physical_source_output']['source_unresolved_graph_pairs'] == 1
    assert result['physical_source_output']['candidate_events_by_source'][10] == []
    assert result['physical_source_output']['edge_events'] == []


def test_no_input_converges_without_fabricating_feedback(monkeypatch):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']],
        'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata, 'manifest': {'fake': 'source'}})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})

    def replay(config, _directories, schedule, _hashes, *, omitted_pairs, solution_sink,
               cell_progress):
        assert not omitted_pairs and schedule['event_count'] == 0
        for done, body in enumerate(config.source_ids, 1):
            solution_sink(body, {}, {})
            cell_progress(done, len(config.source_ids))
        return {'recording': {'cells': len(config.source_ids)}}

    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    stages = []
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
        parameters={}, max_iterations=3, stage_progress=stages.append)
    assert result['status'] == 'converged'
    assert result['feedback_alignment'] == 'schedule_matches_last_replay'
    assert len(result['iterations']) == 1 and result['recording']['cells'] == 2
    assert stages == [{'phase': 'feedback_network', 'iteration': 1, 'done': 0, 'total': 0},
                      {'phase': 'feedback_cells', 'iteration': 1, 'done': 1, 'total': 2},
                      {'phase': 'feedback_cells', 'iteration': 1, 'done': 2, 'total': 2},
                      {'phase': 'feedback_network', 'iteration': 2, 'done': 0, 'total': 0}]


def test_opt_in_discretization_receipts_follow_the_iterated_result(monkeypatch, tmp_path):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64, 'array_sha256': {'ids.npy': 'b' * 64}}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    index = SimpleNamespace(manifest={'ids_sha256': 'b' * 64, 'source_md5': 'c' * 32})
    policy = {'expected_source_md5': 'c' * 32}
    def replay(config, _directories, _schedule, _hashes, *, solution_sink,
               omitted_pairs, discretization_policy, synapse_index):
        assert discretization_policy is policy and synapse_index is index and not omitted_pairs
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}, 'discretization': {'receipt': 'verified'}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, index, [], parameters={},
        max_iterations=3, discretization_policy=policy)
    assert result['status'] == 'converged'
    assert result['discretization_receipts'] == [{'receipt': 'verified'}]
    wrong_index = SimpleNamespace(manifest={'ids_sha256': 'd' * 64, 'source_md5': 'c' * 32})
    with pytest.raises(ValueError, match='index and graph identity mismatch'):
        iterate_population_feedback('archive', fake_graph, wrong_index, [], parameters={},
            max_iterations=3, discretization_policy=policy)
    with pytest.raises(ValueError, match='not supported by feedback checkpoints'):
        iterate_population_feedback('archive', fake_graph, index, [], parameters={},
            max_iterations=3, discretization_policy=policy, checkpoint_dir=tmp_path)

    with pytest.raises(ValueError, match='receipts are not supported'):
        validate_population_feedback(result, fake_graph, {}, parameters={},
                                     allow_partial_geometry=False)


def test_iteration_limit_is_not_reported_as_convergence(monkeypatch):
    # The same empty input needs a second network evaluation to establish stability.
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    calls = []
    def network(*_args, **kwargs):
        calls.append(kwargs['edge_events'])
        return {'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])}
    monkeypatch.setattr(module + 'run_edge_forced_network', network)
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    def replay(config, _directories, _schedule, _hashes, *, omitted_pairs, solution_sink):
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
                                         parameters={}, max_iterations=1)
    assert result['status'] == 'iteration_limit'
    assert result['feedback_alignment'] == 'network_feedback_not_applied_to_last_replay'
    assert result['pending_feedback']['events'] == []
    assert len(calls) == 2
    assert result['physical_source_output']['edge_events'] == calls[-1]
    assert set(result['physical_source_output']['candidate_events_by_source']) == {10, 20}


def test_experimental_cache_is_opt_in_and_scoped_to_each_run(monkeypatch):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    caches = []
    def replay(config, _directories, _schedule, _hashes, *, solution_sink, **options):
        caches.append(options.get('cell_cache'))
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    for budget in (0, 1024, 1024):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
                                    parameters={}, max_iterations=1,
                                    experimental_cache_bytes=budget)
    assert caches[0] is None
    assert caches[1].policy == 'stable' and caches[1].max_bytes == 1024
    assert caches[1] is not caches[2]
    with pytest.raises(ValueError, match='settings'):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
                                    parameters={}, max_iterations=1,
                                    experimental_cache_bytes=True)


def test_experimental_solver_cannot_be_checkpointed_or_published(monkeypatch, tmp_path):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    received = []

    def replay(config, _directories, _schedule, _hashes, *, solution_sink,
               experimental_solver_backend, **kwargs):
        received.append((experimental_solver_backend,
                         kwargs.get('experimental_gpu_output_budget_bytes')))
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': len(config.source_ids)},
                'experimental_gpu_table_clamped_cell_ids': []}

    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback(
        'archive', fake_graph, SimpleNamespace(), [], parameters={}, max_iterations=3,
        experimental_solver_backend='experimental_coreneuron')
    assert result['status'] == 'converged'
    assert result['experimental_solver_backend'] == 'experimental_coreneuron'
    assert received == [('experimental_coreneuron', None)]
    cuda = iterate_population_feedback(
        'archive', fake_graph, SimpleNamespace(), [], parameters={}, max_iterations=3,
        experimental_solver_backend='experimental_cuda', experimental_gpu_output_budget_bytes=1000)
    assert cuda['experimental_solver_backend'] == 'experimental_cuda'
    assert received[-1] == ('experimental_cuda', 1000)
    with pytest.raises(ValueError, match='cannot be published'):
        validate_population_feedback(cuda, fake_graph, {}, parameters={},
                                     allow_partial_geometry=False)
    with pytest.raises(ValueError, match='output budget'):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [], parameters={},
                                    max_iterations=1,
                                    experimental_solver_backend='experimental_cuda')
    with pytest.raises(ValueError, match='cannot be published'):
        validate_population_feedback(result, fake_graph, {}, parameters={},
                                     allow_partial_geometry=False)
    with pytest.raises(ValueError, match='not supported by feedback checkpoints'):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [], parameters={},
            max_iterations=3, checkpoint_dir=tmp_path,
            experimental_solver_backend='experimental_coreneuron')


def test_experimental_workers_are_propagated_but_not_published(monkeypatch, tmp_path):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    received = []

    def replay(config, _directories, _schedule, _hashes, *, solution_sink,
               experimental_cell_workers, **_kwargs):
        received.append(experimental_cell_workers)
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': len(config.source_ids)}}

    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
        parameters={}, max_iterations=3, experimental_cell_workers=2)
    assert result['status'] == 'converged' and result['experimental_cell_workers'] == 2
    assert received == [2]
    with pytest.raises(ValueError, match='cannot be published'):
        validate_population_feedback(result, fake_graph, {}, parameters={},
                                     allow_partial_geometry=False)
    with pytest.raises(ValueError, match='not supported by feedback checkpoints'):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [], parameters={},
            max_iterations=3, checkpoint_dir=tmp_path, experimental_cell_workers=2)


def test_latest_physical_events_are_exported_with_the_network(monkeypatch):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    seen = []
    def network(*_args, **kwargs):
        seen.append(kwargs['edge_events'].copy())
        return {'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])}
    monkeypatch.setattr(module + 'run_edge_forced_network', network)
    monkeypatch.setattr(module + 'suppressed_source_inputs', lambda *_a, **_k: {
        'graph_sha256': 'a' * 64, 'delivery_delay_ms': 2, 'events': []})
    monkeypatch.setattr(module + 'feedback_output_events', lambda body, *_a, **_k: {
        'edge_events': [{'source_id': body, 'target_id': 30, 'tick': 1, 'count': 1}],
        'candidates': [{'partner_id': '30', 'stimulated_ticks_ms': [1]}]})
    def replay(config, _directories, _schedule, _hashes, *, omitted_pairs, solution_sink):
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
                                         parameters={}, max_iterations=1)
    output = result['physical_source_output']
    assert output['edge_events'] == seen[-1] and len(output['edge_events']) == 2
    assert output['candidate_events_by_source'][10][0]['stimulated_ticks_ms'] == [1]
    assert output['graph_sha256'] == 'a' * 64
    assert output['source_morphology_sha256'] == {10: 'b' * 64, 20: 'b' * 64}
    assert len(output['source_configuration_sha256']) == 64
    assert result['feedback_alignment'] == 'network_feedback_not_applied_to_last_replay'


def test_network_spike_is_routed_back_into_population_replay(monkeypatch):
    config = example()
    fake_graph = SimpleNamespace(ids=np.array([10, 20, 30]), size=3,
        ptr=np.array([0, 1, 2, 3]), posts=np.array([1, 2, 1]),
        counts=np.array([1, 1, 2]), signs=np.array([1, -1, 1]),
        provenance={'manifest_sha256': 'a' * 64})
    metadata = {'configuration': config, 'diagnostics': [
        {'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
        for body in config['source_ids']], 'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([2]), 'spike_times_ms': np.array([3.])})
    monkeypatch.setattr(module + 'map_lif_feedback', lambda *_a, **_k: [{
        'source_id': 30, 'target_id': 20, 'input_kind': 'lif-network-spike',
        'graph_sha256': 'a' * 64, 'target_morphology_sha256': 'b' * 64,
        'candidates': [{'target_child_node_id': child, 'target_fraction': .5,
                        'stimulated_ticks_ms': [3]} for child in (7, 8)]}])
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    submitted = []
    def replay(config, _directories, schedule, _hashes, *, omitted_pairs, solution_sink):
        submitted.extend(schedule['events_by_target'][20])
        for body in config.source_ids:
            solution_sink(body, {}, {})
        return {'recording': {'cells': 2}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(), [],
        parameters={1: {'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
        max_iterations=3)
    assert result['status'] == 'converged'
    assert len(submitted) == 2 and {event['time_ms'] for event in submitted} == {5}


def test_iteration_persists_a_verified_snapshot(tmp_path, monkeypatch):
    config = example()
    fake_graph = graph()
    fake_graph.provenance = {'manifest_sha256': 'a' * 64}
    diagnostics = [{'body_id': str(body), 'morphology_sha256': 'b' * 64, 'candidates': []}
                   for body in config['source_ids']]
    metadata = {'configuration': config, 'diagnostics': diagnostics,
                'schedules': [{'edge_events': []}, {'edge_events': []}]}
    module = 'service.application.feedback.loop.'
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata, 'manifest': {'fake': 'source'}})
    monkeypatch.setattr(module + 'run_edge_forced_network', lambda *_a, **_k: {
        'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])})
    monkeypatch.setattr(module + 'feedback_output_events', lambda *_a, **_k: {
        'edge_events': [], 'candidates': []})
    def replay(config, _directories, _schedule, _hashes, *, omitted_pairs, solution_sink):
        for body in config.source_ids:
            solution_sink(body, {}, {})
        count = round(config.simulation.duration_ms / config.simulation.dt_ms) + 1
        time = np.arange(count) * config.simulation.dt_ms
        neural, artifact = 1 + time / 10, 3 + time / 10
        return {'recording': {'cells': 2, 'time_ms': time,
            'neural_uv': neural, 'stimulus_artifact_uv': artifact,
            'stimulus_fraction': np.zeros_like(time), 'total_uv': neural + artifact}}
    monkeypatch.setattr(module + 'replay_population_feedback', replay)
    result = iterate_population_feedback('archive', fake_graph, SimpleNamespace(manifest={}), [],
        parameters={}, max_iterations=1, checkpoint_dir=tmp_path)
    assert result['status'] == 'iteration_limit'
    assert (tmp_path / 'iteration-0001.json').is_file()
    snapshot = json.loads((tmp_path / 'iteration-0001.json').read_text(encoding='utf8'))['payload']
    applied = snapshot['applied_schedule']
    assert applied['events_by_target'] == {'10': [], '20': []}
    assert applied['provenance_by_target'] == {'10': [], '20': []}
    assert applied['unresolved'] == []
    resumed = iterate_population_feedback('archive', fake_graph, SimpleNamespace(manifest={}), [],
        parameters={}, max_iterations=2, checkpoint_dir=tmp_path,
        resume_from=tmp_path / 'iteration-0001.json')
    assert resumed['status'] == 'converged'
    np.testing.assert_allclose(resumed['recording']['neural_uv'][[0, -1]], [1., 2.])
    monkeypatch.setattr(module + 'load_verified_fragment_population',
                        lambda *_: {'metadata': metadata, 'manifest': {'fake': 'changed'}})
    with pytest.raises(ValueError, match='identity'):
        iterate_population_feedback('archive', fake_graph, SimpleNamespace(manifest={}), [],
            parameters={}, max_iterations=2, resume_from=tmp_path / 'iteration-0001.json')
