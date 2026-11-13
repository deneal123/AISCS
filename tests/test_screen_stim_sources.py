import json

import pytest

from scripts.screen_stim_sources import (
    _check_row,
    compute,
    graph_config_from_screen,
    verified_source_cells,
)
from service.domain.contracts.field.graph import FieldGraphConfig


def test_interrupted_screen_resumes_and_verifies_record_chain(tmp_path, monkeypatch):
    calls = []

    def interrupted(ids, _dirs, _simulation, *, threshold_mv):
        calls.append(ids.copy())
        yield {'body_id': ids[0], 'status': 'no_crossing', 'morphology_sha256': 'a' * 64}
        raise RuntimeError('interrupted')

    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells',
                        interrupted)
    args = ([1, 2], [], tmp_path / 'screen.jsonl', {
        'duration_ms': 2, 'current_na': -10., 'source_um': [0, 0, 0],
        'return_um': [10, 0, 0], 'conductivity_s_m': .3, 'clearance_um': 1.,
        'pulse_start_ms': .25, 'pulse_end_ms': .5})
    with pytest.raises(RuntimeError, match='interrupted'):
        compute(*args, threshold_mv=-20., graph_hash='b' * 64)

    def resume(ids, _dirs, _simulation, *, threshold_mv):
        calls.append(ids.copy())
        yield {'body_id': ids[0], 'status': 'source_missing'}

    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells', resume)
    assert compute(*args, threshold_mv=-20., graph_hash='b' * 64) == 2
    assert calls == [[1, 2], [2]]
    assert compute(*args, threshold_mv=-20., graph_hash='b' * 64) == 2
    with pytest.raises(ValueError, match='incompatible provenance'):
        compute(*args, threshold_mv=-20., graph_hash='b' * 64, workers=2)
    for workers in (0, 5, True):
        with pytest.raises(ValueError, match='candidate list'):
            compute(*args, threshold_mv=-20., graph_hash='b' * 64, workers=workers)
    lines = args[2].read_text(encoding='utf8').splitlines()
    row = json.loads(lines[1])
    row['status'] = 'control_crossing'
    lines[1] = json.dumps(row)
    args[2].write_text('\n'.join(lines) + '\n', encoding='utf8')
    with pytest.raises(ValueError, match='checksum'):
        compute(*args, threshold_mv=-20., graph_hash='b' * 64)


def test_invalid_settings_are_rejected_before_file_creation(tmp_path):
    output = tmp_path / 'invalid.jsonl'
    with pytest.raises(ValueError, match='parameters'):
        compute([1], [], output, {'duration_ms': 2, 'current_na': 0.},
                threshold_mv=-20., graph_hash='b' * 64)
    assert not output.exists()


def test_disconnected_status_blocks_network_readiness(tmp_path, monkeypatch):
    def screen(ids, _dirs, _simulation, *, threshold_mv):
        yield {'body_id': ids[0], 'status': 'disconnected_morphology'}

    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells', screen)
    params = {'duration_ms': 2, 'current_na': -10., 'source_um': [0, 0, 0],
              'return_um': [10, 0, 0], 'conductivity_s_m': .3, 'clearance_um': 1.,
              'pulse_start_ms': .25, 'pulse_end_ms': .5}
    path = tmp_path / 'disconnected.jsonl'
    compute([1], [], path, params, threshold_mv=-20., graph_hash='b' * 64)
    result = verified_source_cells([1], path, params, threshold_mv=-20., graph_hash='b' * 64)
    assert result['unresolved'] == [{'body_id': 1, 'status': 'disconnected_morphology'}]
    assert not result['network_ready']


def test_rejects_unmatched_sample_and_event_tick():
    row = {'body_id': 1, 'status': 'stimulus_only_crossing', 'morphology_sha256': 'a' * 64,
           'selection': {'child_node_id': 10, 'sampling_fraction': .5, 'segment_index': 2,
                         'first_sample_ms': .5, 'event_ticks_ms': [1],
                         'interpretation': ('earliest sampled threshold crossing; '
                                            'not a validated spike')}}
    _check_row(row, 1, 2, .25)
    row['selection']['event_ticks_ms'] = [2]
    with pytest.raises(ValueError, match='timing'):
        _check_row(row, 1, 2, .25)
    row['selection']['event_ticks_ms'] = [1]
    row['selection']['first_sample_ms'] = .51
    with pytest.raises(ValueError, match='timing'):
        _check_row(row, 1, 2, .25)


def test_complete_screen_can_form_checked_graph_configuration(tmp_path, monkeypatch):
    template = {
        'graph_manifest_sha256': 'b' * 64,
        'source_cells': [{'body_id': 10, 'child_node_id': 1, 'threshold_mv': -20.}],
        'replay_ids': [20], 'seed': 1,
        'simulation': {'source_um': [0, 0, 0], 'return_um': [100, 0, 0],
            'electrode_um': [0, 50, 0], 'reference_um': [100, 50, 0], 'current_na': -10,
            'conductivity_s_m': .3, 'clearance_um': 1, 'duration_ms': 10, 'dt_ms': .05,
            'pulse_start_ms': 2, 'pulse_end_ms': 3, 'rise_time_ms': .2,
            'interphase_gap_ms': 0, 'pulse_shape': 'monophasic', 'nseg_per_edge': 1,
            'allow_disconnected': False, 'source_model': 'pointsource',
            'coordinate_frame': 'male-cns-v1.0-native-um'},
        'synapse': {'delay_ms': 2, 'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2,
                    'reversal_mv': 0}}
    simulation = FieldGraphConfig.model_validate(template).execution_parameters()[
        'simulation_parameters']

    def screen(ids, _dirs, _simulation, *, threshold_mv, field_coupling='extracellular'):
        assert ids == [1, 2]
        extra = {'fallback_runs': 0} if field_coupling == 'virtual_current' else {}
        yield {'body_id': 1, 'status': 'stimulus_only_crossing', 'morphology_sha256': 'a' * 64,
               'selection': {'child_node_id': 5, 'sampling_fraction': .5, 'segment_index': 0,
                             'first_sample_ms': 2.25, 'event_ticks_ms': [3],
                             'interpretation': ('earliest sampled threshold crossing; '
                                                'not a validated spike')}, **extra}
        yield {'body_id': 2, 'status': 'no_crossing', 'morphology_sha256': 'c' * 64, **extra}

    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells', screen)
    path = tmp_path / 'complete.jsonl'
    compute([1, 2], [], path, simulation, threshold_mv=-20., graph_hash='b' * 64)
    result = graph_config_from_screen([1, 2], path, template, threshold_mv=-20.)
    assert result['screened'] == 2
    assert result['configuration']['source_cells'] == [
        {'body_id': 1, 'child_node_id': 5, 'sampling_fraction': .5,
         'threshold_mv': -20., 'morphology_sha256': 'a' * 64}]
    invalid = {**template, 'replay_ids': [1]}
    with pytest.raises(ValueError):
        graph_config_from_screen([1, 2], path, invalid, threshold_mv=-20.)
    partial = tmp_path / 'partial.jsonl'
    partial.write_text('\n'.join(path.read_text(encoding='utf8').splitlines()[:-1]) + '\n')
    with pytest.raises(ValueError, match='footer'):
        graph_config_from_screen([1, 2], partial, template, threshold_mv=-20.)

    def unresolved(ids, _dirs, _simulation, *, threshold_mv):
        yield {'body_id': ids[0], 'status': 'source_missing'}
        yield {'body_id': ids[1], 'status': 'no_crossing', 'morphology_sha256': 'c' * 64}

    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells',
                        unresolved)
    unknown = tmp_path / 'unknown.jsonl'
    compute([1, 2], [], unknown, simulation, threshold_mv=-20., graph_hash='b' * 64)
    with pytest.raises(ValueError, match='unresolved'):
        graph_config_from_screen([1, 2], unknown, template, threshold_mv=-20.)
    monkeypatch.setattr('scripts.screen_stim_sources.source_screening.screen_source_cells', screen)
    experimental = tmp_path / 'experimental.jsonl'
    compute([1, 2], [], experimental, simulation, threshold_mv=-20., graph_hash='b' * 64,
            field_coupling='virtual_current')
    with pytest.raises(ValueError, match='not approved'):
        graph_config_from_screen([1, 2], experimental, template, threshold_mv=-20.)
