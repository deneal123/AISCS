import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.infrastructure.stimulation.feedback.checkpoint import (
    checkpoint_run_identity,
    read_checkpoint,
    validate_checkpoint,
    write_checkpoint,
)
from tests.test_fragment_population_contract import example


def sample():
    config = FragmentPopulationConfig.model_validate(example())
    time = [index * config.simulation.dt_ms for index in
            range(round(config.simulation.duration_ms / config.simulation.dt_ms) + 1)]
    neural = [1. + value / 10 for value in time]
    artifact = [3. + value / 10 for value in time]
    def diagnostic(body, partner, position):
        return {'body_id': str(body), 'candidates': [{'included_in_graph': True,
                'partner_id': str(partner), 'source_position_8nm': position}]}
    diagnostics = {10: diagnostic(10, 30, [1, 2, 3]), 20: diagnostic(20, 30, [4, 5, 6])}
    state = {'format': 'population-feedback-checkpoint-v1', 'configuration_sha256': config.digest(),
        'graph_sha256': config.graph_manifest_sha256, 'source_ids': [10, 20],
        'run_identity': 'd' * 64,
        'allow_partial_geometry': False, 'parameters': {'1': {'weight_us': .001}},
        'history': [{'iteration': 1, 'schedule_sha256': 'b' * 64}],
        'local': {'10': [{'partner_id': '30', 'source_position_8nm': [1, 2, 3],
                          'stimulated_ticks_ms': [1]}],
                  '20': [{'partner_id': '30', 'source_position_8nm': [4, 5, 6],
                          'stimulated_ticks_ms': []}]},
        'edges': [{'source_id': 10, 'target_id': 30, 'tick': 1, 'count': 1}],
        'recording': {'cells': 2, 'time_ms': time, 'neural_uv': neural,
                      'stimulus_artifact_uv': artifact, 'stimulus_fraction': [0.] * len(time),
                      'total_uv': [a + b for a, b in zip(neural, artifact, strict=True)]}}
    return config, diagnostics, state


def test_immutable_checkpoint_verifies_identity_and_contents(tmp_path):
    config, diagnostics, state = sample()
    path = tmp_path / 'iteration.json'
    write_checkpoint(path, state)
    assert read_checkpoint(path, config=config, diagnostics=diagnostics,
                           parameters={1: {'weight_us': .001}},
                           allow_partial_geometry=False, run_identity='d' * 64) == state
    with pytest.raises(FileExistsError):
        write_checkpoint(path, state)
    assert read_checkpoint(path, config=config, diagnostics=diagnostics,
                           parameters={1: {'weight_us': .001}},
                           allow_partial_geometry=False, run_identity='d' * 64) == state
    envelope = json.loads(path.read_text())
    envelope['payload']['edges'][0]['count'] = 2
    path.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='checksum'):
        read_checkpoint(path, config=config, diagnostics=diagnostics,
                        parameters={1: {'weight_us': .001}}, allow_partial_geometry=False,
                        run_identity='d' * 64)


def test_checkpoint_does_not_invent_crossings_for_unresolved_source_geometry():
    _, diagnostics, state = sample()
    config = FragmentPopulationConfig.model_validate({**example(), 'allow_partial_geometry': True})
    diagnostics[10]['candidates'][0]['centerline_distance_um'] = .1
    diagnostics[20]['candidates'][0]['centerline_distance_um'] = 2.1
    state['configuration_sha256'] = config.digest()
    state['allow_partial_geometry'] = True
    state['local']['20'] = []
    params = {1: {'weight_us': .001}}
    validate_checkpoint(state, config=config, diagnostics=diagnostics, parameters=params,
                        allow_partial_geometry=True, run_identity='d' * 64)
    state['local']['20'] = [{'partner_id': '30', 'source_position_8nm': [4, 5, 6],
                             'stimulated_ticks_ms': []}]
    with pytest.raises(ValueError, match='Incomplete checkpoint source'):
        validate_checkpoint(state, config=config, diagnostics=diagnostics, parameters=params,
                            allow_partial_geometry=True, run_identity='d' * 64)


def test_failed_publication_does_not_leave_partial_checkpoint(tmp_path, monkeypatch):
    _, _, state = sample()
    path = tmp_path / 'iteration.json'
    def fail_link(*_args):
        raise OSError('simulated publication interruption')
    monkeypatch.setattr('service.infrastructure.stimulation.feedback.checkpoint.os.link',
                        fail_link)
    with pytest.raises(OSError, match='simulated publication interruption'):
        write_checkpoint(path, state)
    assert not path.exists()
    assert not list(tmp_path.iterdir())


def test_concurrent_writers_cannot_overwrite_checkpoint(tmp_path):
    _, _, state = sample()
    path = tmp_path / 'iteration.json'
    def save(marker):
        try:
            write_checkpoint(path, {**state, 'marker': marker})
            return 'published'
        except FileExistsError:
            return 'exists'
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(save, ('first', 'second')))
    assert sorted(outcomes) == ['exists', 'published']
    assert json.loads(path.read_text(encoding='utf-8'))['payload']['marker'] in ('first', 'second')
    assert list(tmp_path.iterdir()) == [path]


def test_rejects_inconsistent_events_and_recording():
    config, diagnostics, state = sample()
    state['edges'][0]['count'] = 2
    with pytest.raises(ValueError, match='edge events'):
        validate_checkpoint(state, config=config, diagnostics=diagnostics,
                            parameters={1: {'weight_us': .001}}, allow_partial_geometry=False,
                            run_identity='d' * 64)
    state['edges'][0]['count'] = 1
    state['recording']['total_uv'][0] = 0.
    with pytest.raises(ValueError, match='recording'):
        validate_checkpoint(state, config=config, diagnostics=diagnostics,
                            parameters={1: {'weight_us': .001}}, allow_partial_geometry=False,
                            run_identity='d' * 64)


def test_rejects_recording_with_missing_or_off_grid_samples():
    config, diagnostics, state = sample()
    args = dict(config=config, diagnostics=diagnostics, parameters={1: {'weight_us': .001}},
                allow_partial_geometry=False, run_identity='d' * 64)
    state['recording']['time_ms'][100] += .001
    with pytest.raises(ValueError, match='recording'):
        validate_checkpoint(state, **args)
    for array in ('time_ms', 'neural_uv', 'stimulus_artifact_uv', 'stimulus_fraction', 'total_uv'):
        state['recording'][array].pop(100)
    with pytest.raises(ValueError, match='recording'):
        validate_checkpoint(state, **args)


def test_applied_schedule_is_bound_to_last_iteration():
    config, diagnostics, state = sample()
    applied = {'graph_sha256': config.graph_manifest_sha256, 'source_ids': config.source_ids,
               'events_by_target': {'10': [], '20': []},
               'provenance_by_target': {'10': [], '20': []}, 'target_morphology_sha256': {},
               'event_count': 0, 'outside_window': 0, 'unresolved': []}
    signature = hashlib.sha256(json.dumps({'events': applied['events_by_target'],
        'unresolved': applied['unresolved']}, sort_keys=True, separators=(',', ':'),
        allow_nan=False).encode()).hexdigest()
    state['applied_schedule'] = applied
    state['history'][-1]['schedule_sha256'] = signature
    state['history'][-1].update(input_events=0, outside_window=0, unresolved_events=0)
    args = dict(config=config, diagnostics=diagnostics, parameters={1: {'weight_us': .001}},
                allow_partial_geometry=False, run_identity='d' * 64)
    assert validate_checkpoint(state, **args) is state
    applied['events_by_target']['10'].append({'time_ms': 3.})
    with pytest.raises(ValueError, match='applied schedule'):
        validate_checkpoint(state, **args)


def test_applied_schedule_validates_event_provenance_and_parameters():
    config, diagnostics, state = sample()
    kinetic = {'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    state['parameters'] = {'1': kinetic}
    event = {'child_node_id': 7, 'position': .5, 'time_ms': 5, **kinetic}
    origin = {'source_id': 20, 'candidate_index': 0, 'source_tick_ms': 3}
    applied = {'graph_sha256': config.graph_manifest_sha256, 'source_ids': config.source_ids,
               'events_by_target': {'10': [event], '20': []},
               'provenance_by_target': {'10': [origin], '20': []}, 'target_morphology_sha256': {},
               'event_count': 1, 'outside_window': 0, 'unresolved': []}
    state['applied_schedule'] = applied
    state['history'][-1].update(input_events=1, outside_window=0, unresolved_events=0)
    state['history'][-1]['schedule_sha256'] = hashlib.sha256(json.dumps(
        {'events': applied['events_by_target'], 'unresolved': []}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    args = dict(config=config, diagnostics=diagnostics, parameters={1: kinetic},
                allow_partial_geometry=False, run_identity='d' * 64)
    assert validate_checkpoint(state, **args) is state
    origin['source_tick_ms'] = 4
    with pytest.raises(ValueError, match='event provenance'):
        validate_checkpoint(state, **args)
    origin['source_tick_ms'] = 3
    event['weight_us'] = .002
    with pytest.raises(ValueError, match='event provenance'):
        validate_checkpoint(state, **args)


def test_checkpoint_detects_tampered_observation_provenance():
    config, diagnostics, state = sample()
    kinetic = {'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    state['parameters'] = {'1': kinetic}
    event = {'child_node_id': 7, 'position': 1., 'time_ms': 5, **kinetic}
    origin = {'source_id': 20, 'candidate_index': 0, 'source_tick_ms': 3,
              'target_position_8nm': [100, 200, 300], 'target_distance_um': .075,
              'source_position_8nm': [10, 20, 30]}
    provenance = {'10': [origin], '20': []}
    applied = {'graph_sha256': config.graph_manifest_sha256, 'source_ids': config.source_ids,
               'events_by_target': {'10': [event], '20': []},
               'provenance_by_target': provenance, 'target_morphology_sha256': {},
               'event_count': 1, 'outside_window': 0, 'unresolved': []}
    applied['provenance_sha256'] = hashlib.sha256(json.dumps(
        provenance, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    state['applied_schedule'] = applied
    state['history'][-1].update(input_events=1, outside_window=0, unresolved_events=0)
    state['history'][-1]['schedule_sha256'] = hashlib.sha256(json.dumps(
        {'events': applied['events_by_target'], 'unresolved': []}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    args = dict(config=config, diagnostics=diagnostics, parameters={1: kinetic},
                allow_partial_geometry=False, run_identity='d' * 64)
    assert validate_checkpoint(state, **args) is state
    origin['target_position_8nm'][0] = 101
    with pytest.raises(ValueError, match='provenance differs'):
        validate_checkpoint(state, **args)


def test_identity_binds_both_input_manifests():
    original = checkpoint_run_identity({'source': 'a'}, {'index': 'b'})
    assert original != checkpoint_run_identity({'source': 'changed'}, {'index': 'b'})
    assert original != checkpoint_run_identity({'source': 'a'}, {'index': 'changed'})
