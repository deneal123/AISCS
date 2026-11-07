import numpy as np
import pytest

from service.application.screening.source_screening import screen_source_cells
from service.infrastructure.stimulation.swc_reference import DisconnectedMorphologyError

BASE = {'source_um': [0., 0., 0.], 'return_um': [10., 0., 0.],
        'conductivity_s_m': .3, 'clearance_um': 1., 'pulse_start_ms': .25, 'pulse_end_ms': .5}


def test_paired_screen_keeps_negative_ambiguous_and_missing_separate(monkeypatch):
    def solve(body, _directories, **params):
        assert params['record_membrane_current'] is False
        if body == 4:
            raise FileNotFoundError()
        values = np.full((1, 5), -65.)
        if body == 1 and params['current_na'] != 0 or body == 2:
            values[0, 1:3] = 10.
        return ({'time_ms': np.array([0., .5, 1., 1.5, 2.]),
                 'voltage_mv': values, 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': 'a' * 64, 'components': 1})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    settings = {**BASE, 'duration_ms': 2, 'current_na': -10.}
    rows = list(screen_source_cells([1, 2, 3, 4], [], settings, threshold_mv=-20.))
    assert [row['status'] for row in rows] == ['stimulus_only_crossing', 'control_crossing',
                                                'no_crossing', 'source_missing']
    assert rows[0]['selection']['child_node_id'] == 77
    assert rows[0]['selection']['event_ticks_ms'] == [1]


def test_changed_morphology_and_bad_input_fail_closed(monkeypatch):
    def solve(body, _directories, **params):
        return ({'time_ms': np.array([0., .5, 1.]), 'voltage_mv': np.full((1, 3), -65.),
                 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': ('a' if params['current_na'] else 'b') * 64,
                 'components': 1})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 1, 'current_na': -10.},
                                    threshold_mv=-20.))
    assert rows == [{'body_id': 1, 'status': 'invalid_or_ambiguous'}]
    for candidates, current in (([1, 1], -10.), ([1], 0.), ([True], -10.)):
        with pytest.raises(ValueError):
            list(screen_source_cells(candidates, [], {'duration_ms': 1, 'current_na': current},
                                     threshold_mv=-20.))
    with pytest.raises(ValueError, match='solver settings'):
        list(screen_source_cells([1], [], {**BASE, 'duration_ms': 1, 'current_na': -10.,
                                         'dt_ms': 0.}, threshold_mv=-20.))


def test_disconnected_morphology_remains_explicitly_unresolved(monkeypatch):
    def solve(*_args, **_kwargs):
        raise DisconnectedMorphologyError('fragment connections are unknown')

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    for method in ('extracellular', 'virtual_current'):
        rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 1, 'current_na': -10.},
                                        threshold_mv=-20., field_coupling=method))
        assert rows[0]['status'] == 'disconnected_morphology'
        assert rows[0].get('fallback_runs', 0) == 0


def test_fragment_simulation_cannot_make_screen_network_ready(monkeypatch):
    def solve(body, _directories, **_kwargs):
        return ({'time_ms': np.array([0., .5, 1.]), 'voltage_mv': np.full((1, 3), -65.),
                 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': 'a' * 64, 'components': 2})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 1, 'current_na': -10.,
                                             'allow_disconnected': True}, threshold_mv=-20.))
    assert rows == [{'body_id': 1, 'status': 'disconnected_morphology'}]


def test_missing_component_provenance_fails_closed(monkeypatch):
    def solve(body, _directories, **_kwargs):
        return ({'time_ms': np.array([0., .5, 1.]), 'voltage_mv': np.full((1, 3), -65.),
                 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': 'a' * 64})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 1, 'current_na': -10.},
                                    threshold_mv=-20.))
    assert rows == [{'body_id': 1, 'status': 'invalid_or_ambiguous'}]


def test_virtual_screen_recalculates_near_threshold_with_reference(monkeypatch):
    calls = []

    def solve(body, _directories, **params):
        method = params.get('field_coupling', 'extracellular')
        calls.append((params['current_na'], method))
        values = np.full((1, 5), -65.)
        if params['current_na'] != 0:
            values[0, 1] = -20. - 1e-9 if method == 'virtual_current' else -20. + 1e-9
        return ({'time_ms': np.array([0., .5, 1., 1.5, 2.]),
                 'voltage_mv': values, 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': 'a' * 64, 'components': 1})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 2, 'current_na': -10.},
                                    threshold_mv=-20., field_coupling='virtual_current'))
    assert rows[0]['status'] == 'stimulus_only_crossing'
    assert rows[0]['fallback_runs'] == 1
    assert calls == [(-10., 'virtual_current'), (-10., 'extracellular'), (0., 'virtual_current')]


def test_failed_reference_fallback_is_not_reported_as_no_crossing(monkeypatch):
    def solve(body, _directories, **params):
        if params.get('field_coupling') != 'virtual_current':
            raise ValueError('reference unavailable')
        values = np.full((1, 5), -65.)
        values[0, 1] = -20. - 1e-9
        return ({'time_ms': np.array([0., .5, 1., 1.5, 2.]),
                 'voltage_mv': values, 'edge_node_ids': np.array([77])},
                {'body_id': body, 'morphology_sha256': 'a' * 64, 'components': 1})

    monkeypatch.setattr('service.application.screening.source_screening.simulate_registered_swc_reference',
                        solve)
    rows = list(screen_source_cells([1], [], {**BASE, 'duration_ms': 2, 'current_na': -10.},
                                    threshold_mv=-20., field_coupling='virtual_current'))
    assert rows == [{'body_id': 1, 'status': 'invalid_or_ambiguous', 'fallback_runs': 1}]
