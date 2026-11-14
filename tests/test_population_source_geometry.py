from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.population.source_geometry import (
    source_geometry_diagnostics,
)


def inputs():
    geometry = {'edge_node_ids': np.array([7, 9]),
        'starts_um': np.array([[0., 0., 0.], [10., 0., 0.]]),
        'ends_um': np.array([[2., 0., 0.], [12., 0., 0.]]),
        'endpoint_radii_um': np.array([[.1, .1], [.1, .1]])}
    cell = {'id': 10, 'morphology_sha256': 'b' * 64, 'geometry': geometry}
    graph = SimpleNamespace(posts=np.array([1]), provenance={
        'manifest_sha256': 'a' * 64, 'array_sha256': {'ids.npy': 'c' * 64}})
    pairs = [{'body_pre': 10, 'body_post': 20, 'x_pre': 125, 'y_pre': 0, 'z_pre': 0},
             {'body_pre': 10, 'body_post': 20, 'x_pre': 1375, 'y_pre': 500, 'z_pre': 0}]
    page = {'source_md5': 'd' * 32, 'pairs': pairs, 'total': 2, 'returned': 2,
            'truncated': False}
    index = SimpleNamespace(manifest={'ids_sha256': 'c' * 64, 'source_md5': 'd' * 32},
                            query=lambda *_a, **_k: page)
    return cell, graph, index, page


def test_registered_geometry_keeps_unresolved_candidates_unknown(monkeypatch):
    cell, graph, index, _ = inputs()
    monkeypatch.setattr('service.infrastructure.stimulation.population.source_geometry.outgoing',
        lambda *_a: {'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    result = source_geometry_diagnostics(cell, graph, index, threshold_mv=-20., duration_ms=10,
        simulation_sha256='e' * 64, max_distance_um=2.)
    first, second = result['candidates']
    assert result['graph_pairs'] == 2 and first['result_segment_index'] == 0
    assert first['status'] == 'timing_or_trace_ambiguous' and first['stimulated_ticks_ms'] is None
    assert second['result_segment_index'] == 1 and second['status'] == 'geometry_unresolved'
    assert second['stimulated_ticks_ms'] is None and second['control_ticks_ms'] is None

    from service.application.feedback.outputs import (
        feedback_output_segment_indices,
        feedback_selected_output_ticks,
        merge_archived_source_events,
    )

    provenance = {'body_id': '10', 'morphology_sha256': 'b' * 64}
    indices = feedback_output_segment_indices(10, cell['geometry']['edge_node_ids'],
        provenance, result, threshold_mv=-20., duration_ms=10, max_source_distance_um=2.)
    assert indices == [0]
    archived = feedback_selected_output_ticks(10, cell['geometry']['edge_node_ids'], {0: [2]},
        provenance, result, threshold_mv=-20., duration_ms=10, max_source_distance_um=2.,
        include_candidates=True, include_unresolved_candidates=True)
    merged = merge_archived_source_events(result, archived)
    assert merged['candidates'][0]['stimulated_ticks_ms'] == [2]
    assert merged['candidates'][1]['status'] == 'geometry_unresolved'


def test_rejects_incomplete_and_mismatched_source(monkeypatch):
    cell, graph, index, page = inputs()
    monkeypatch.setattr('service.infrastructure.stimulation.population.source_geometry.outgoing',
        lambda *_a: {'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    kwargs = dict(threshold_mv=-20., duration_ms=10, simulation_sha256='e' * 64,
                  max_distance_um=2.)
    page['truncated'] = True
    with pytest.raises(ValueError, match='Incomplete source synapse'):
        source_geometry_diagnostics(cell, graph, index, **kwargs)
    page['truncated'] = False
    page['pairs'].pop()
    page['total'] = page['returned'] = 1
    with pytest.raises(ValueError, match='counts do not match'):
        source_geometry_diagnostics(cell, graph, index, **kwargs)


def test_store_reuses_verified_geometry_and_rejects_corruption(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.population.source_store import SourceDiagnosticsStore

    cell, graph, index, _ = inputs()
    monkeypatch.setattr('service.infrastructure.stimulation.population.source_geometry.outgoing',
        lambda *_a: {'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    with SourceDiagnosticsStore(tmp_path / 'source.db', graph, index, threshold_mv=-20.,
            duration_ms=10, simulation_sha256='e' * 64, max_distance_um=2.,
            morphology_sha256={10: 'b' * 64}) as store:
        initial = store.metadata([cell])
        assert initial['diagnostics'][10]['graph_pairs'] == 2
        assert store.diagnostics((10,)) == initial['diagnostics']
        index.query = lambda *_a, **_k: pytest.fail('cached diagnostics were recomputed')
        assert store.metadata([cell]) == initial
        refined = {**cell, 'geometry': {**cell['geometry'],
            'edge_node_ids': np.array([7, 7, 7, 9]),
            'grid': [(7, 0, 3), (7, 1, 3), (7, 2, 3), (9, 0, 1)]}}
        receipt = store.metadata([refined])
        assert receipt['diagnostics'] == initial['diagnostics']
        assert receipt['provenance'][10]['configuration'] == {
            'nseg_per_edge': 1, 'nseg_by_edge': {'7': 3}}
        from service.application.feedback.outputs import feedback_output_segment_indices

        assert feedback_output_segment_indices(10, refined['geometry']['edge_node_ids'],
            receipt['provenance'][10], receipt['diagnostics'][10], threshold_mv=-20.,
            duration_ms=10, max_source_distance_um=2.) == [1]
        refined['geometry']['grid'] = [(7, 0, 3), (7, 2, 3), (7, 1, 3), (9, 0, 1)]
        with pytest.raises(ValueError, match='event grid'):
            store.metadata([refined])
        index.manifest['source_md5'] = 'f' * 32
        with pytest.raises(ValueError, match='dataset identity changed'):
            store.diagnostics((10,))
        index.manifest['source_md5'] = 'd' * 32
        with pytest.raises(ValueError, match='identity'):
            store.metadata([{**cell, 'morphology_sha256': 'f' * 64}])
        store.db.execute('UPDATE sources SET payload = ?', (b'{}',))
        with pytest.raises(ValueError, match='corrupted'):
            store.diagnostics((10,))


def test_source_store_accepts_producer_and_consumer_threads(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from service.infrastructure.stimulation.population.source_store import SourceDiagnosticsStore

    cell, graph, index, _ = inputs()
    monkeypatch.setattr('service.infrastructure.stimulation.population.source_geometry.outgoing',
        lambda *_a: {'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    with SourceDiagnosticsStore(tmp_path / 'source.db', graph, index, threshold_mv=-20.,
            duration_ms=10, simulation_sha256='e' * 64, max_distance_um=2.,
            morphology_sha256={10: 'b' * 64}) as store:
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(lambda _: store.metadata([cell]), range(6)))
        assert all(receipt == receipts[0] for receipt in receipts)
        assert store.diagnostics((10,)) == receipts[0]['diagnostics']
