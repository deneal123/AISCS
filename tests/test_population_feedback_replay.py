from copy import deepcopy

import pytest

from service.application.feedback.cell_cache import CellSolutionCache
from service.application.feedback.replay import replay_population_feedback
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from tests.test_fragment_population_contract import example


def setup():
    config = FragmentPopulationConfig.model_validate(example())
    hashes = {10: 'b' * 64, 20: 'c' * 64}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: [{'child_node_id': 7}]},
                'target_morphology_sha256': {20: 'c' * 64}, 'event_count': 1}
    return config, hashes, schedule


def test_replays_complete_population_and_supplies_only_each_targets_events(monkeypatch):
    config, hashes, schedule = setup()
    seen = []

    def simulate(body, _directories, *, expected_morphology_sha256, synaptic_events, **_settings):
        seen.append((body, synaptic_events, expected_morphology_sha256))
        return {}, {'body_id': str(body), 'morphology_sha256': expected_morphology_sha256}

    def record(records, *_args, **_kwargs):
        return {'cells': len(list(records))}

    module = 'service.application.feedback.replay.'
    monkeypatch.setattr(module + 'simulate_registered_swc_reference', simulate)
    monkeypatch.setattr(module + 'record_independent_cells', record)
    result = replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[(10, 20)])
    assert [item[0] for item in seen] == [10, 20]
    assert seen[0][1] == [] and seen[1][1] == [{'child_node_id': 7}]
    assert result['recording']['cells'] == 2 and result['incomplete_pairs'] == [(10, 20)]


def test_rejects_incompatible_morphology_and_event_coverage():
    config, hashes, schedule = setup()
    modified = deepcopy(schedule)
    modified['target_morphology_sha256'][20] = 'd' * 64
    with pytest.raises(ValueError, match='morphology identity'):
        replay_population_feedback(config, [], modified, hashes, omitted_pairs=[])
    modified = deepcopy(schedule)
    modified['event_count'] = 2
    with pytest.raises(ValueError, match='event count'):
        replay_population_feedback(config, [], modified, hashes, omitted_pairs=[])
    modified = deepcopy(schedule)
    modified['unresolved'] = [{'source_id': 10, 'target_id': 20}]
    with pytest.raises(ValueError, match='Unreported'):
        replay_population_feedback(config, [], modified, hashes, omitted_pairs=[])


@pytest.mark.parametrize('position', [0., 1.])
def test_rejects_endpoint_before_running_any_population_cell(monkeypatch, position):
    config, hashes, schedule = setup()
    schedule['events_by_target'][20][0]['position'] = position

    def unexpected(*_args, **_kwargs):
        raise AssertionError('A physical cell was started before endpoint validation')

    monkeypatch.setattr('service.application.feedback.replay.'
                        'simulate_registered_swc_reference', unexpected)
    with pytest.raises(ValueError, match='zero-area section endpoint'):
        replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[])


def test_explicit_verified_discretization_reaches_solver_and_is_returned(monkeypatch):
    config, hashes, schedule = setup()
    schedule['events_by_target'][20][0]['position'] = 1.
    prepared = {'targets': {20: {'effective_events': [{'child_node_id': 7, 'position': .9}],
                                  'nseg_by_edge': {'7': 5}, 'sha256': 'd' * 64}},
                'observation_audit': {'verified_events': 1}}
    seen = []
    module = 'service.application.feedback.replay.'
    monkeypatch.setattr(module + 'prepare_feedback_discretization', lambda *_a, **_k: prepared)
    def simulate(body, _directories, *, expected_morphology_sha256, synaptic_events, **settings):
        seen.append((body, synaptic_events, settings.get('nseg_by_edge')))
        return {}, {'body_id': str(body), 'morphology_sha256': expected_morphology_sha256}
    monkeypatch.setattr(module + 'simulate_registered_swc_reference', simulate)
    monkeypatch.setattr(module + 'record_independent_cells',
                        lambda records, *_a, **_k: {'cells': len(list(records))})
    policy = {'expected_source_md5': 'e' * 32, 'max_shift_um': 2.,
              'max_observation_distance_um': 2., 'max_nseg': 5}
    result = replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
                                        discretization_policy=policy, synapse_index=object())
    assert seen[1] == (20, [{'child_node_id': 7, 'position': .9}], {'7': 5})
    assert result['discretization'] == prepared
    assert schedule['events_by_target'][20][0]['position'] == 1.


def test_discretization_policy_requires_index_and_explicit_bounds():
    config, hashes, schedule = setup()
    with pytest.raises(ValueError, match='policy and index'):
        replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
                                   discretization_policy={}, synapse_index=object())


def test_run_local_cache_reuses_only_unchanged_cell_inputs(monkeypatch):
    config, hashes, schedule = setup()
    calls = []
    module = 'service.application.feedback.replay.'

    def simulate(body, _directories, *, expected_morphology_sha256, **_settings):
        calls.append(body)
        return {'result': [body]}, {'body_id': str(body),
                                   'morphology_sha256': expected_morphology_sha256,
                                   'morphology_source': 'verified-source'}

    monkeypatch.setattr(module + 'simulate_registered_swc_reference', simulate)
    monkeypatch.setattr(module + 'record_independent_cells',
                        lambda records, *_a, **_k: {'cells': len(list(records))})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a, **_k: {'source': 'verified-source'})
    cache = CellSolutionCache(100_000)
    replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[], cell_cache=cache)
    changed = deepcopy(schedule)
    changed['events_by_target'][20][0]['child_node_id'] = 8
    replay_population_feedback(config, [], changed, hashes, omitted_pairs=[], cell_cache=cache)
    assert calls == [10, 20, 20]
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a, **_k: {'source': 'changed-source'})
    with pytest.raises(ValueError, match='provenance mismatch'):
        replay_population_feedback(config, [], changed, hashes, omitted_pairs=[], cell_cache=cache)


def test_experimental_solver_is_explicit_and_isolated_in_cache(monkeypatch):
    config, hashes, schedule = setup()
    calls = []
    module = 'service.application.feedback.replay.'

    def simulate(body, _directories, *, expected_morphology_sha256, **settings):
        calls.append((body, settings.get('solver_backend'), settings.get('field_coupling')))
        return {'result': [body]}, {'body_id': str(body),
                                   'morphology_sha256': expected_morphology_sha256,
                                   'morphology_source': 'verified-source'}

    monkeypatch.setattr(module + 'simulate_registered_swc_reference', simulate)
    monkeypatch.setattr(module + 'record_independent_cells',
                        lambda records, *_a, **_k: {'cells': len(list(records))})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a, **_k: {'source': 'verified-source'})
    cache = CellSolutionCache(100_000)
    ordinary = replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
                                          cell_cache=cache)
    experimental = replay_population_feedback(
        config, [], schedule, hashes, omitted_pairs=[], cell_cache=cache,
        experimental_solver_backend='experimental_coreneuron')
    assert 'experimental_solver_backend' not in ordinary
    assert experimental['experimental_solver_backend'] == 'experimental_coreneuron'
    assert calls == [(10, None, None), (20, None, None),
                     (10, 'experimental_coreneuron', 'experimental_virtual_current'),
                     (20, 'experimental_coreneuron', 'experimental_virtual_current')]
    with pytest.raises(ValueError, match='experimental solver backend'):
        replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
                                   experimental_solver_backend=True)
