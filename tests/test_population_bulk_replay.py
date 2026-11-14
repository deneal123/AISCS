import numpy as np
import pytest

from service.application.feedback.fixed_inputs import fixed_input_digest
from service.application.feedback.population_bulk_replay import (
    replay_bulk_feedback,
    replay_verified_feedback_to_archive,
)
from tests.test_fixed_feedback_inputs import fixture as schedule_fixture
from tests.test_windowed_feedback_outputs import collector


def test_bulk_feedback_stages_events_and_recording(monkeypatch):
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10], 'morphology_sha256': 'a'}
    staged = []

    def solve(metadata, stimulus, rate_table, *, event_factory, device_window_factory, **kwargs):
        assert event_factory((10,)) == {10: []}
        device = device_window_factory([cell])
        voltage = [-65.] * 41
        voltage[20] = -10.
        device['sink'](0, 41, [{'id': 10, 'neural_uv': [1.] * 41,
                                'selected_voltage_mv': [voltage]}])
        yield [10], {'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.solve_population',
                        solve)
    options = dict(audited_sources={}, params=None, expected_ids=[10], events_by_target={10: []},
        metadata_factory=lambda cells: {'provenance': source.provenance,
                                        'diagnostics': source.diagnostics},
        event_sink=staged.append, time_ms=np.arange(41) * .05, threshold_mv=-20.,
        duration_ms=2, electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
        conductivity_s_m=.3, clearance_um=1., segment_budget=10, output_budget_bytes=10000)
    result = replay_bulk_feedback(None, [0.] * 41, None, **options)
    np.testing.assert_array_equal(result['neural_uv'], np.ones(41))
    assert result['cells'] == 1
    assert staged[0][10]['edge_events'][0]['target_id'] == 20
    def incorrect_receipt(metadata, stimulus, rate_table, **kwargs):
        yield [10], {'table_clamped_cell_ids': []}
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.solve_population',
                        incorrect_receipt)
    with pytest.raises(ValueError, match='receipt does not match'):
        replay_bulk_feedback(None, [0.] * 41, None, **options)
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.solve_population',
                        solve)
    calls = []
    def events(batch):
        calls.append(batch)
        return {10: []}
    replay_bulk_feedback(None, [0.] * 41, None, **{**options, 'events_by_target': events})
    assert calls == [(10,)]
    with pytest.raises(ValueError, match='event batch'):
        replay_bulk_feedback(None, [0.] * 41, None,
                             **{**options, 'events_by_target': lambda batch: {}})
    with pytest.raises(ValueError, match='bulk feedback replay inputs'):
        replay_bulk_feedback(None, [0.] * 41, None, **{**options, 'events_by_target': {}})
    with pytest.raises(ValueError, match='time grid'):
        replay_bulk_feedback(None, [0.] * 41, None,
                             **{**options, 'time_ms': np.arange(41) * .025})


def test_bulk_feedback_rejects_missing_solver_receipt(monkeypatch):
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.solve_population',
                        lambda *a, **k: iter([([10], {})]))
    with pytest.raises(ValueError, match='clamped HH'):
        replay_bulk_feedback(None, [0.] * 21, None, audited_sources={}, params=None,
            expected_ids=[10], events_by_target={10: []}, metadata_factory=lambda cells: {},
            event_sink=lambda result: None, time_ms=np.arange(21) * .05,
            threshold_mv=-20., duration_ms=1,
            electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.], conductivity_s_m=.3,
            clearance_um=1., segment_budget=10, output_budget_bytes=10000)


def test_verified_replay_checks_inputs_before_atomic_publication(monkeypatch, tmp_path):
    schedule, hashes = schedule_fixture()
    digest = fixed_input_digest(schedule)
    destination = tmp_path / 'events.jsonl'
    destination.write_text('previous', encoding='utf8')
    source = collector()
    source.provenance[10]['morphology_sha256'] = hashes[10]
    source.diagnostics[10]['morphology_sha256'] = hashes[10]
    cell = {'id': 10, 'geometry': source.geometries[10], 'morphology_sha256': hashes[10]}

    def solve(metadata, stimulus, rate_table, *, event_factory, device_window_factory, **kwargs):
        assert event_factory((10, 20))[20] == [{'child_node_id': 7}]
        device_window_factory([cell])
        raise RuntimeError('solver failed')
        yield  # pragma: no cover

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.solve_population',
                        solve)
    options = dict(audited_sources={}, params=None, expected_ids=[10, 20],
        metadata_factory=lambda cells: {'provenance': source.provenance,
                                        'diagnostics': source.diagnostics},
        time_ms=np.arange(41) * .05, threshold_mv=-20., duration_ms=2,
        electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.], conductivity_s_m=.3,
        clearance_um=1., segment_budget=10, output_budget_bytes=10000)
    args = ({'graph_sha256': 'a' * 64}, [0.] * 41, None)
    with pytest.raises(RuntimeError, match='solver failed'):
        replay_verified_feedback_to_archive(*args, schedule=schedule, schedule_sha256=digest,
            morphology_sha256=hashes, event_path=destination, **options)
    assert destination.read_text(encoding='utf8') == 'previous'
    assert sorted(tmp_path.iterdir()) == [destination]
    cell['morphology_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='morphology digest'):
        replay_verified_feedback_to_archive(*args, schedule=schedule, schedule_sha256=digest,
            morphology_sha256=hashes, event_path=destination, **options)
    assert destination.read_text(encoding='utf8') == 'previous'


@pytest.mark.parametrize('position', [0., 1.])
def test_verified_replay_rejects_endpoint_before_gpu_launch(monkeypatch, tmp_path, position):
    schedule, hashes = schedule_fixture()
    schedule['events_by_target'][20][0]['position'] = position
    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'replay_bulk_feedback_to_archive',
                        lambda *args, **kwargs: pytest.fail('GPU must not start'))
    with pytest.raises(ValueError, match='Unresolved feedback endpoint in target cell 20'):
        replay_verified_feedback_to_archive({'graph_sha256': 'a' * 64}, [], None,
            schedule=schedule, schedule_sha256=fixed_input_digest(schedule),
            morphology_sha256=hashes, event_path=tmp_path / 'events.jsonl',
            metadata_factory=lambda cells: {}, expected_ids=[10, 20])
    assert list(tmp_path.iterdir()) == []


def test_verified_replay_passes_checked_schedule_and_records_identity(monkeypatch, tmp_path):
    schedule, hashes = schedule_fixture()
    digest = fixed_input_digest(schedule)

    def replay(metadata, stimulus, rate_table, *, events_by_target, metadata_factory, **kwargs):
        assert events_by_target((10, 20)) == schedule['events_by_target']
        assert metadata_factory([{'id': 10, 'morphology_sha256': hashes[10]}]) == 'verified'
        original = hashes[10]
        hashes[10] = 'd' * 64
        with pytest.raises(ValueError, match='morphology digest'):
            metadata_factory([{'id': 10, 'morphology_sha256': hashes[10]}])
        assert metadata_factory([{'id': 10, 'morphology_sha256': original}]) == 'verified'
        return {'event_sha256': 'e' * 64}

    monkeypatch.setattr('service.application.feedback.population_bulk_replay.'
                        'replay_bulk_feedback_to_archive', replay)
    result = replay_verified_feedback_to_archive({'graph_sha256': 'a' * 64}, [], None,
        schedule=schedule, schedule_sha256=digest, morphology_sha256=hashes,
        event_path=tmp_path / 'events.jsonl', metadata_factory=lambda cells: 'verified',
        expected_ids=[10, 20])
    assert result['fixed_input_schedule_sha256'] == digest
    assert result['fixed_input_graph_sha256'] == 'a' * 64
