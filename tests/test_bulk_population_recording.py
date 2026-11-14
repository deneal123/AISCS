import numpy as np
import pytest

from service.application.feedback.fixed_inputs import fixed_input_digest
from service.application.population.bulk_recording import (
    run_bulk_recording,
    run_fixed_input_recording,
    run_verified_fixed_input_recording,
)
from tests.test_windowed_feedback_outputs import collector


def options():
    return dict(audited_sources={}, params=None, expected_ids=[10],
        time_ms=np.arange(41) * .05, electrode_um=[10., 0., 0.],
        reference_um=[20., 0., 0.], conductivity_s_m=.3, clearance_um=1.,
        segment_budget=10, output_budget_bytes=10000)


def test_independent_recording_requires_all_verified_solver_receipts(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10]}

    def solve(_metadata, _stimulus, _table, *, device_window_factory, **_kwargs):
        recorder = device_window_factory([cell])
        recorder['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    result = run_bulk_recording(None, [0.] * 41, None, **options())
    np.testing.assert_array_equal(result['neural_uv'], np.ones(41))
    assert result['cells'] == 1 and 'no network feedback' in result['interpretation']
    assert result['replacement_receipts'] == []


def test_replacement_receipt_is_returned_only_after_complete_recording(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10]}
    transformation = {'source_sha256': 'a' * 64, 'derived_sha256': 'b' * 64}

    def solve(_metadata, _stimulus, _table, *, device_window_factory, on_replacement, **_kwargs):
        on_replacement(10, 7, transformation)
        recorder = device_window_factory([cell])
        recorder['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    result = run_bulk_recording(None, [0.] * 41, None, **options(),
                                replacement_factory=lambda *_: None)
    assert result['replacement_receipts'] == [
        {'body_id': 10, 'error_code': 7, 'transformation': transformation}]
    transformation['source_sha256'] = 'changed'
    assert result['replacement_receipts'][0]['transformation']['source_sha256'] == 'a' * 64


def test_independent_recording_rejects_partial_receipt_and_clamp(monkeypatch):
    def solve(*_args, **_kwargs):
        yield [10], {'table_clamped_cell_ids': [10]}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    with pytest.raises(ValueError, match='clamped'):
        run_bulk_recording(None, [0.] * 41, None, **options())
    with pytest.raises(ValueError, match='time grid'):
        run_bulk_recording(None, [0.] * 41, None,
                           **{**options(), 'time_ms': np.arange(41) * .025})
    with pytest.raises(ValueError, match='owns solver callbacks'):
        run_bulk_recording(None, [0.] * 41, None, **options(), on_invalid=lambda *_: None)


def test_progress_reports_only_validated_batches(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10]}
    updates = []

    def solve(_metadata, _stimulus, _table, *, device_window_factory, **_kwargs):
        recorder = device_window_factory([cell])
        recorder['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    run_bulk_recording(None, [0.] * 41, None, **options(),
                       progress=lambda *value: updates.append(value))
    assert updates == [('independent_cells', 0, 1), ('independent_cells', 1, 1)]

    def clamped(*_args, **_kwargs):
        yield [10], {'table_clamped_cell_ids': [10]}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', clamped)
    updates.clear()
    with pytest.raises(ValueError, match='clamped'):
        run_bulk_recording(None, [0.] * 41, None, **options(),
                           progress=lambda *value: updates.append(value))
    assert updates == [('independent_cells', 0, 1)]


def test_fixed_input_recording_is_explicit_and_does_not_claim_feedback(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10]}

    def solve(_metadata, _stimulus, _table, *, device_window_factory, event_factory, **_kwargs):
        assert event_factory((10,)) == {10: ['fixed']}
        recorder = device_window_factory([cell])
        recorder['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    result = run_fixed_input_recording(None, [0.] * 41, None, **options(),
                                       event_factory=lambda _: {10: ['fixed']})
    assert 'fixed external event schedule' in result['interpretation']
    assert 'no network feedback' in result['interpretation']
    with pytest.raises(ValueError, match='fixed input'):
        run_fixed_input_recording(None, [0.] * 41, None, **options(), event_factory=None)


def test_verified_fixed_input_rejects_changed_schedule_before_solver(monkeypatch):
    import hashlib

    provenance_sha = hashlib.sha256(b'{"10":[]}').hexdigest()
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10],
        'target_morphology_sha256': {}, 'events_by_target': {10: []},
        'provenance_by_target': {10: []}, 'provenance_sha256': provenance_sha,
        'event_count': 0, 'unresolved': []}
    digest = fixed_input_digest(schedule)
    schedule['event_count'] = 1
    monkeypatch.setattr('service.application.population.bulk_recording.solve_population',
                        lambda *_a, **_k: pytest.fail('solver must not run'))
    with pytest.raises(ValueError, match='schedule digest'):
        run_verified_fixed_input_recording({'graph_sha256': 'a' * 64}, [0.] * 41, None,
            **options(), schedule=schedule, schedule_sha256=digest,
            morphology_sha256={10: 'b' * 64})


def test_fixed_input_can_stream_selected_voltages(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10]}
    received = []

    def solve(_metadata, _stimulus, _table, *, device_window_factory,
              recording_max_selected, **_kwargs):
        assert recording_max_selected == 1
        recorder = device_window_factory([cell])
        assert recorder['selected_indices'] == {10: [0]}
        recorder['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41,
                                  'selected_voltage_mv': [[-65.] * 41]}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.population.bulk_recording.solve_population', solve)
    run_fixed_input_recording(None, [0.] * 41, None, **options(), event_factory=lambda _: {10: []},
        _selection_factory=lambda _: {10: [0]},
        _selected_sink=lambda start, end, rows, _: received.append((start, end, rows)),
        _max_selected=1)
    assert received[0][0:2] == (0, 41)
    assert received[0][2][0]['selected_voltage_mv'][0] == [-65.] * 41
