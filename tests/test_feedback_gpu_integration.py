import pytest

from service.application.feedback.replay import replay_population_feedback
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from tests.test_fragment_population_contract import example


def test_gpu_feedback_replay_preserves_order_and_provenance(monkeypatch):
    config = FragmentPopulationConfig.model_validate(example())
    hashes = {10: '1' * 64, 20: '2' * 64}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: []}, 'target_morphology_sha256': {},
                'event_count': 0}
    captured = []

    def gpu(requests, directories, simulation, *, output_budget_bytes):
        assert [item['id'] for item in requests] == [10, 20]
        assert output_budget_bytes == 1000
        return [{'id': item['id'], 'morphology_sha256': item['expected_sha256'],
                 'arrays': {'body': item['id']},
                 'provenance': {'body_id': str(item['id']),
                                'experimental_hh_table_clamped': False}} for item in requests]

    def record(records, *args, **kwargs):
        captured.extend(records)
        return {'cells': len(captured)}

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', gpu)
    monkeypatch.setattr('service.application.feedback.replay.record_independent_cells', record)
    progress = []
    result = replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
        experimental_solver_backend='experimental_cuda', experimental_gpu_output_budget_bytes=1000,
        cell_progress=lambda done, total: progress.append((done, total)))
    assert result['experimental_solver_backend'] == 'experimental_cuda'
    assert [row[0]['body'] for row in captured] == [10, 20]
    assert progress == [(1, 2), (2, 2)]


def test_gpu_feedback_replay_requires_explicit_budget():
    config = FragmentPopulationConfig.model_validate(example())
    with pytest.raises(ValueError, match='budget'):
        replay_population_feedback(config, [], {}, {}, omitted_pairs=[],
                                   experimental_solver_backend='experimental_cuda')


def test_gpu_feedback_reports_clamped_cells(monkeypatch):
    config = FragmentPopulationConfig.model_validate(example())
    hashes = {10: '1' * 64, 20: '2' * 64}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: []}, 'target_morphology_sha256': {},
                'event_count': 0}

    def gpu(requests, _directories, _simulation, **kwargs):
        assert kwargs['allow_table_clamp'] is True
        return [{'id': item['id'], 'morphology_sha256': item['expected_sha256'], 'arrays': {},
                 'provenance': {'body_id': str(item['id']),
                                'experimental_hh_table_clamped': item['id'] == 20}}
                for item in requests]

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', gpu)
    monkeypatch.setattr('service.application.feedback.replay.record_independent_cells',
                        lambda rows, *_a, **_k: {'cells': len(list(rows))})
    result = replay_population_feedback(
        config, [], schedule, hashes, omitted_pairs=[],
        experimental_solver_backend='experimental_cuda',
        experimental_gpu_output_budget_bytes=1000, experimental_gpu_allow_table_clamp=True)
    assert result['experimental_gpu_table_clamped_cell_ids'] == [20]


def test_gpu_progress_reports_solver_windows(monkeypatch):
    config = FragmentPopulationConfig.model_validate(example())
    hashes = {10: '1' * 64, 20: '2' * 64}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: []}, 'target_morphology_sha256': {},
                'event_count': 0}

    def gpu(requests, _directories, _simulation, **kwargs):
        kwargs['progress'](25, 100)
        kwargs['progress'](100, 100)
        return [{'id': item['id'], 'morphology_sha256': item['expected_sha256'], 'arrays': {},
                 'provenance': {'body_id': str(item['id']),
                                'experimental_hh_table_clamped': False}}
                for item in requests]

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', gpu)
    monkeypatch.setattr('service.application.feedback.replay.record_independent_cells',
                        lambda rows, *_a, **_k: {'cells': len(list(rows))})
    progress = []
    replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
        experimental_solver_backend='experimental_cuda', experimental_gpu_output_budget_bytes=1000,
        gpu_progress=lambda done, total: progress.append((done, total)))
    assert progress == [(25, 100), (100, 100)]


def test_windowed_feedback_uses_integer_graph_duration_and_ordered_sources(monkeypatch):
    config = FragmentPopulationConfig.model_validate(example())
    hashes = {10: '1' * 64, 20: '2' * 64}
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
                'events_by_target': {10: [], 20: []}, 'target_morphology_sha256': {},
                'event_count': 0}
    diagnostics, received = {10: {}, 20: {}}, []

    def replay(requests, directories, simulation, provided, **kwargs):
        assert type(kwargs['duration_ms']) is int
        assert list(provided) == [10, 20]
        assert kwargs['preparation_workers'] == 2
        return {'sources': {10: {'edge_events': []}, 20: {'edge_events': []}},
                'table_clamped_cell_ids': [], 'recording': {}}

    monkeypatch.setattr('service.application.feedback.windowed_replay.replay_windowed_sources',
                        replay)
    result = replay_population_feedback(config, [], schedule, hashes, omitted_pairs=[],
        experimental_solver_backend='experimental_cuda', experimental_gpu_output_budget_bytes=1000,
        experimental_gpu_stream_cells=2, experimental_gpu_window_steps=5,
        experimental_gpu_preparation_workers=2,
        windowed_diagnostics=diagnostics,
        windowed_output_sink=lambda body, events: received.append(body))
    assert received == [10, 20]
    assert result['recording']['cell_provenance_fields_present'] is False


def test_windowed_feedback_rejects_incompatible_callbacks():
    config = FragmentPopulationConfig.model_validate(example())
    with pytest.raises(ValueError, match='windowed replay options'):
        replay_population_feedback(config, [], {}, {}, omitted_pairs=[],
            experimental_solver_backend='experimental_cuda',
            experimental_gpu_output_budget_bytes=1000, experimental_gpu_stream_cells=2,
            experimental_gpu_window_steps=5, windowed_diagnostics={10: {}, 20: {}},
            solution_sink=lambda *args: None)


def test_device_reduction_requires_windowed_replay():
    config = FragmentPopulationConfig.model_validate(example())
    with pytest.raises(ValueError, match='Windowed replay options'):
        replay_population_feedback(config, [], {}, {}, omitted_pairs=[],
            experimental_solver_backend='experimental_cuda',
            experimental_gpu_output_budget_bytes=1000, experimental_gpu_device_reduction=True)


def test_parallel_preparation_requires_windowed_cuda():
    config = FragmentPopulationConfig.model_validate(example())
    with pytest.raises(ValueError, match='Parallel GPU preparation'):
        replay_population_feedback(config, [], {}, {}, omitted_pairs=[],
                                   experimental_gpu_preparation_workers=2)
