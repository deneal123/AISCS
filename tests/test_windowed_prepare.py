import pytest

from service.application.feedback.cell_cache import CellSolutionCache
from service.application.feedback.windowed_prepare import prepare_windowed_sources


def test_bounded_sources_validate_provenance_and_disconnected_policy(monkeypatch):
    digest = 'a' * 64
    request = {'id': 1, 'expected_sha256': digest, 'events': [], 'nseg_by_edge': {}}
    simulation = {'dt_ms': .05, 'allow_disconnected': True, 'nseg_per_edge': 1,
                  'source_um': [0, 0, 0], 'return_um': [1, 0, 0], 'current_na': 1,
                  'conductivity_s_m': .3, 'clearance_um': 1, 'duration_ms': 10}
    monkeypatch.setattr('service.application.feedback.windowed_prepare.prepare_hh_table',
                        lambda: ('table', 'gates'))
    monkeypatch.setattr('service.application.feedback.windowed_prepare.prepare_registered_cell',
        lambda body, directories, **kwargs: {'id': body, 'components': 2,
            'morphology_sha256': kwargs['expected_sha256'], 'morphology_source': 'source'})
    prepared = prepare_windowed_sources([request], [], simulation, max_cells=1)
    assert prepared['provenance'][1]['morphology_sha256'] == digest
    assert prepared['provenance'][1]['configuration']['synaptic_events'] == []
    assert prepared['cells'][0]['initial_gates'] == 'gates'
    with pytest.raises(ValueError, match='Disconnected'):
        prepare_windowed_sources([request], [], {**simulation, 'allow_disconnected': False},
                                 max_cells=1)
    with pytest.raises(ValueError, match='bounded'):
        prepare_windowed_sources([request], [], simulation, max_cells=0)


def test_cached_geometry_rechecks_source_and_refreshes_events(monkeypatch):
    digest = 'a' * 64
    request = {'id': 1, 'expected_sha256': digest, 'events': [], 'nseg_by_edge': {}}
    simulation = {'dt_ms': .05, 'allow_disconnected': True, 'nseg_per_edge': 1,
                  'source_um': [0, 0, 0], 'return_um': [1, 0, 0], 'current_na': 1,
                  'conductivity_s_m': .3, 'clearance_um': 1, 'duration_ms': 10}
    calls = []
    monkeypatch.setattr('service.application.feedback.windowed_prepare.prepare_hh_table',
                        lambda: ('table', 'gates'))

    def prepare(body, directories, **kwargs):
        calls.append(body)
        return {'id': body, 'components': 1, 'morphology_sha256': digest,
                'morphology_source': 'source', 'geometry': {'grid': [(7, 0, 1)]}, 'events': []}

    monkeypatch.setattr('service.application.feedback.windowed_prepare.prepare_registered_cell',
                        prepare)
    monkeypatch.setattr('service.application.feedback.windowed_prepare.read_skeleton',
                        lambda *args, **kwargs: {'source': 'source'})
    cache = CellSolutionCache(100000, policy='stable')
    prepare_windowed_sources([request], [], simulation, max_cells=1, geometry_cache=cache)
    prepare_windowed_sources([request], [], simulation, max_cells=1, geometry_cache=cache)
    assert calls == [1]
    monkeypatch.setattr('service.application.feedback.windowed_prepare.read_skeleton',
                        lambda *args, **kwargs: {'source': 'other'})
    with pytest.raises(ValueError, match='provenance'):
        prepare_windowed_sources([request], [], simulation, max_cells=1, geometry_cache=cache)


def test_parallel_preparation_preserves_order_and_rejects_cache_combination(monkeypatch):
    digest = 'a' * 64
    requests = [{'id': body, 'expected_sha256': digest, 'events': [], 'nseg_by_edge': {}}
                for body in (2, 1)]
    simulation = {'dt_ms': .05, 'allow_disconnected': True, 'nseg_per_edge': 1,
                  'source_um': [0, 0, 0], 'return_um': [1, 0, 0], 'current_na': 1,
                  'conductivity_s_m': .3, 'clearance_um': 1, 'duration_ms': 10}
    monkeypatch.setattr('service.application.feedback.windowed_prepare.prepare_hh_table',
                        lambda: ('table', 'gates'))
    def prepare_batch(batch, directories, *, workers):
        assert workers == 2
        return [{'id': row['body_id'], 'components': 1, 'morphology_sha256': digest,
                 'morphology_source': 'source'} for row in batch]
    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.prepare_batches.'
                        'prepare_registered_batch', prepare_batch)
    result = prepare_windowed_sources(requests, [], simulation, max_cells=2, preparation_workers=2)
    assert [cell['id'] for cell in result['cells']] == [2, 1]
    assert list(result['provenance']) == [2, 1]
    with pytest.raises(ValueError, match='bounded'):
        prepare_windowed_sources(requests, [], simulation, max_cells=2, preparation_workers=2,
                                 geometry_cache=CellSolutionCache(1000))
