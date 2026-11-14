import hashlib
import json
from types import SimpleNamespace

import pytest

from service.application.population.bulk_experiment import execute_bulk_experiment
from tests.test_fragment_population_contract import example


def test_experiment_checks_cache_and_uses_registered_population(tmp_path, monkeypatch):
    module = 'service.application.population.bulk_experiment.'
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'a' * 64})
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'b' * 64}
    sources = {10: 'c' * 64, 20: 'd' * 64}
    monkeypatch.setattr(module + 'audited_geometry_sources', lambda *args: (sources, 'e' * 64))
    seen = {}

    def manifest(directory, **kwargs):
        seen['manifest'] = (directory, kwargs)
        return {'graph_sha256': 'a' * 64}

    def execute(metadata, stimulus, table, **kwargs):
        seen['execute'] = (metadata, stimulus, table, kwargs)
        return {'artifact': 'verified'}

    monkeypatch.setattr(module + 'read_manifest', manifest)
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: ('table', 'gates'))
    monkeypatch.setattr(module + 'execute_bulk_recording', execute)
    result = execute_bulk_experiment(graph, example()['simulation'], geometry_cache=cache,
        output_path=tmp_path / 'trace.npz', solver_options={'segment_budget': 200})
    assert result == {'artifact': 'verified', 'geometry_cache_manifest_sha256': 'b' * 64,
                      'source_index_sha256': 'e' * 64}
    assert seen['manifest'][1]['source_index_sha256'] == 'e' * 64
    kwargs = seen['execute'][3]
    assert kwargs['expected_ids'] == [10, 20]
    assert kwargs['audited_sources'] is sources
    assert kwargs['segment_budget'] == 200
    assert len(kwargs['configuration_sha256']) == 64
    assert kwargs['electrode_um'] == [0., 50., 0.]


def test_configuration_digest_matches_backend_canonical_json():
    from service.domain.contracts.population.bulk_recording import BulkRecordingConfig

    config = BulkRecordingConfig(graph_manifest_sha256='a' * 64,
                                 simulation=example()['simulation'])
    serialized = json.dumps(config.model_dump(mode='json'), sort_keys=True,
                            separators=(',', ':'), allow_nan=False).encode('utf8')
    assert config.digest() == hashlib.sha256(serialized).hexdigest()


def test_experiment_rejects_mismatched_cache_before_computing(tmp_path, monkeypatch):
    module = 'service.application.population.bulk_experiment.'
    graph = SimpleNamespace(ids=[10], provenance={'manifest_sha256': 'a' * 64})
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'b' * 64}
    monkeypatch.setattr(module + 'audited_geometry_sources', lambda *args: ({10: 'c' * 64},
                                                                            'd' * 64))
    def reject(*args, **kwargs):
        raise ValueError('cache mismatch')
    monkeypatch.setattr(module + 'read_manifest', reject)
    with pytest.raises(ValueError, match='cache mismatch'):
        execute_bulk_experiment(graph, example()['simulation'], geometry_cache=cache,
                                output_path=tmp_path / 'trace.npz', solver_options={})
    assert not (tmp_path / 'trace.npz').exists()


def test_known_invalid_geometry_is_rejected_before_expensive_run(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
        KNOWN_SOURCE_SHA256,
    )

    module = 'service.application.population.bulk_experiment.'
    graph = SimpleNamespace(ids=[842998], provenance={'manifest_sha256': 'a' * 64})
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'b' * 64}
    monkeypatch.setattr(module + 'audited_geometry_sources',
                        lambda *args: ({842998: KNOWN_SOURCE_SHA256}, 'd' * 64))
    monkeypatch.setattr(module + 'read_manifest', lambda *args, **kwargs: {})
    def unexpected():
        raise AssertionError('No solver preparation expected')
    monkeypatch.setattr(module + 'prepare_hh_table', unexpected)
    with pytest.raises(ValueError, match='requires explicit verified repair'):
        execute_bulk_experiment(graph, example()['simulation'], geometry_cache=cache,
                                output_path=tmp_path / 'trace.npz', solver_options={})
