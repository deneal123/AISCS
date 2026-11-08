import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.field.field_proxy_preview import field_proxy_preview
from service.infrastructure.execution.process import (
    _file_sha256,
    _valid_progress,
    run_field_proxy_child,
)


def payload():
    return {'execution_id': '00000000-0000-0000-0000-000000000001', 'config': {
        'graph_manifest_sha256': 'a' * 64, 'coordinate_frame': 'male-cns-v1.0-native-um',
        'source_um': [0., 0., 0.], 'return_um': [10., 0., 0.], 'current_na': -300.,
        'conductivity_s_m': .3, 'clearance_um': 1., 'gain': 1., 'seed': 1,
        'waveform': [0., 1., 0.], 'allow_partial_geometry': False,
        'allow_missing_curvature': False}}


def test_preview_reports_actual_events_without_fabricating_recording():
    graph = SimpleNamespace(size=3)
    run = {'spike_times_ms': np.array([1, 2, 2]), 'spike_neurons': np.array([0, 0, 2]),
           'counts': np.array([2, 0, 1]), 'control_spike_times_ms': np.array([2]),
           'control_spike_neurons': np.array([1]), 'control_counts': np.array([0, 1, 0])}
    provenance = {'excluded_from_direct_field': ['one'], 'excluded_contact_intersections': []}
    preview = field_proxy_preview(graph, run, [0, 1, 0], provenance)
    assert preview['spikes_by_ms'] == [0, 1, 2, 0]
    assert preview['control_spikes_by_ms'] == [0, 0, 1, 0]
    assert preview['active_neurons'] == 2
    assert preview['direct_field_exclusions'] == 1
    assert preview['recording'] is None
    with pytest.raises(ValueError, match='event summary'):
        field_proxy_preview(graph, {**run, 'spike_times_ms': np.array([4])}, [0, 1, 0], provenance)


@pytest.mark.parametrize('changed', [
    {'counts': np.array([1, 1, 1])},
    {'spike_neurons': np.array([0, 1, 0])},
    {'spike_neurons': np.array([0, 0, 0])},
    {'spike_neurons': np.array([0, 0, 3])},
    {'spike_neurons': np.array([0., 0., 2.])},
    {'control_counts': np.array([1, 0, 0])},
    {'control_spike_neurons': np.array([3])},
    {'control_spike_times_ms': np.array([0])},
])
def test_preview_rejects_inconsistent_neuron_identity_order_or_control(changed):
    graph = SimpleNamespace(size=3)
    run = {'spike_times_ms': np.array([1, 2, 2]), 'spike_neurons': np.array([0, 0, 2]),
           'counts': np.array([2, 0, 1]), 'control_spike_times_ms': np.array([2]),
           'control_spike_neurons': np.array([1]), 'control_counts': np.array([0, 1, 0])}
    provenance = {'excluded_from_direct_field': [], 'excluded_contact_intersections': []}
    with pytest.raises(ValueError, match='field-proxy event'):
        field_proxy_preview(graph, {**run, **changed}, [0, 1, 0], provenance)


def test_preview_rejects_an_incomplete_control_triplet():
    run = {'spike_times_ms': np.array([], dtype=float), 'spike_neurons': np.array([], dtype=int),
           'counts': np.zeros(3, dtype=int), 'control_spike_times_ms': np.array([])}
    with pytest.raises(ValueError, match='Incomplete field-proxy event'):
        field_proxy_preview(SimpleNamespace(size=3), run, [0], {})


def test_preview_checks_event_order_across_chunk_boundaries(monkeypatch):
    monkeypatch.setattr('service.application.field.field_proxy_preview._EVENT_CHECK_BLOCK', 2)
    run = {'spike_times_ms': np.array([1, 2, 2]), 'spike_neurons': np.array([0, 2, 1]),
           'counts': np.array([1, 1, 1])}
    with pytest.raises(ValueError, match='event order'):
        field_proxy_preview(SimpleNamespace(size=3), run, [0, 1], {})


def test_invalid_network_counts_are_rejected_before_artifact_creation(tmp_path, monkeypatch):
    from service.application.field.field_proxy_execution import execute_field_proxy

    graph = SimpleNamespace(size=2, ids=np.array([1, 2]),
                            provenance={'manifest_sha256': 'a' * 64})
    provenance = {'excluded_from_direct_field': [], 'excluded_contact_intersections': []}
    monkeypatch.setattr('service.application.field.field_proxy_execution.verified_descriptors',
                        lambda *_args, **_kwargs: (np.zeros(2), provenance))
    monkeypatch.setattr('service.infrastructure.connectome.field_proxy.run_field_proxy',
                        lambda *_args, **_kwargs: {'spike_neurons': np.array([0]),
                            'spike_times_ms': np.array([1]), 'counts': np.array([0, 1])})
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='field-proxy event summary'):
        execute_field_proxy(graph, [], field_path=tmp_path / 'field', output=output,
                            configuration={}, gain=1, seed=1, waveform=[1])
    assert not output.exists()


def test_disagreeing_sparse_and_sampled_network_states_are_rejected(tmp_path, monkeypatch):
    from service.application.field.field_proxy_execution import execute_field_proxy
    from service.infrastructure.connectome import field_proxy
    from tests.test_field_proxy import graph as make_graph

    graph = make_graph()
    graph.provenance = {'manifest_sha256': 'a' * 64}
    provenance = {'excluded_from_direct_field': [], 'excluded_contact_intersections': [],
                  'file_sha256': 'b' * 64}
    monkeypatch.setattr('service.application.field.field_proxy_execution.verified_descriptors',
                        lambda *_args, **_kwargs: (np.array([1., -1.]), provenance))
    original = field_proxy.run_field_proxy

    def inconsistent(*args, **kwargs):
        run = original(*args, **kwargs)
        run['target_response']['active_relative_mv'][1, 0] += 1
        return run

    monkeypatch.setattr(field_proxy, 'run_field_proxy', inconsistent)
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='Sparse snapshot difference mismatch'):
        execute_field_proxy(graph, [], field_path=tmp_path / 'field', output=output,
                            configuration={}, gain=20, seed=1, waveform=[0, 1, 0],
                            capture_delta=True)
    assert not (output / 'state-delta.bin').exists()
    assert not (output / 'metadata.json').exists()


def test_unknown_sparse_status_cannot_be_published_as_success(tmp_path, monkeypatch):
    from service.application.field.field_proxy_execution import execute_field_proxy
    from service.infrastructure.connectome import field_proxy
    from tests.test_field_proxy import graph as make_graph

    graph = make_graph()
    graph.provenance = {'manifest_sha256': 'a' * 64}
    provenance = {'excluded_from_direct_field': [], 'excluded_contact_intersections': [],
                  'file_sha256': 'b' * 64}
    monkeypatch.setattr('service.application.field.field_proxy_execution.verified_descriptors',
                        lambda *_args, **_kwargs: (np.array([1., -1.]), provenance))
    original = field_proxy.run_field_proxy

    def inconsistent(*args, **kwargs):
        run = original(*args, **kwargs)
        run['sparse_delta'] = {'status': 'unknown'}
        return run

    monkeypatch.setattr(field_proxy, 'run_field_proxy', inconsistent)
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='Invalid sparse result status'):
        execute_field_proxy(graph, [], field_path=tmp_path / 'field', output=output,
                            configuration={}, gain=20, seed=1, waveform=[0, 1, 0],
                            capture_delta=True)
    assert not (output / 'metadata.json').exists()


def test_artifact_hashing_streams_without_reading_the_whole_file(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    data = b'network-data' * 10000
    path = tmp_path / 'network-events.bin'
    path.write_bytes(data)
    monkeypatch.setattr(Path, 'read_bytes', lambda _self: pytest.fail('whole-file read'))
    assert _file_sha256(path) == hashlib.sha256(data).hexdigest()


def test_executor_uses_bounded_configured_field_workers(tmp_path, monkeypatch):
    import sys

    observed = []

    def execute(_graph, _dirs, *, output, field_workers, **_options):
        observed.append(field_workers)
        output.mkdir()
        (output / 'metadata.json').write_text('{}')

    monkeypatch.setitem(sys.modules, 'service.application.field.field_proxy_execution',
                        SimpleNamespace(execute_field_proxy=execute))
    monkeypatch.setitem(sys.modules, 'service.infrastructure.connectome.neighbors',
                        SimpleNamespace(registered_graph=lambda: SimpleNamespace(
                            provenance={'manifest_sha256': 'a' * 64})))
    monkeypatch.setitem(sys.modules, 'service.settings',
                        SimpleNamespace(morphology_directories=lambda: []))
    monkeypatch.setenv('GENERATOR_FIELD_WORKERS', '2')
    run_field_proxy_child(payload(), str(tmp_path / 'output'))
    assert observed == [2]
    monkeypatch.setattr('service.infrastructure.execution.process.mp.current_process',
                        lambda: SimpleNamespace(daemon=True))
    run_field_proxy_child(payload(), str(tmp_path / 'daemon-output'))
    assert observed == [2, 1]
    monkeypatch.setenv('GENERATOR_FIELD_WORKERS', '9')
    with pytest.raises(ValueError, match='worker count'):
        run_field_proxy_child(payload(), str(tmp_path / 'invalid'))
    assert observed == [2, 1]


def test_executor_forwards_explicit_field_backend_without_silent_fallback(tmp_path, monkeypatch):
    observed = []

    def execute(_graph, _dirs, *, output, field_workers, field_backend, **_options):
        observed.append((field_workers, field_backend))
        output.mkdir()
        (output / 'metadata.json').write_text('{}')

    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.settings.morphology_directories', lambda: [])
    monkeypatch.setattr('service.application.field.field_proxy_execution.execute_field_proxy',
                        execute)
    monkeypatch.setenv('GENERATOR_FIELD_WORKERS', '1')
    monkeypatch.setenv('GENERATOR_FIELD_BACKEND', 'gpu')
    run_field_proxy_child(payload(), str(tmp_path / 'output'))
    assert observed == [(1, 'gpu')]
    monkeypatch.setenv('GENERATOR_FIELD_WORKERS', '2')
    run_field_proxy_child(payload(), str(tmp_path / 'parallel-gpu'))
    assert observed == [(1, 'gpu'), (2, 'gpu')]
    monkeypatch.setenv('GENERATOR_FIELD_BACKEND', 'unknown')
    with pytest.raises(ValueError, match='Invalid field backend'):
        run_field_proxy_child(payload(), str(tmp_path / 'invalid-backend'))
    assert observed == [(1, 'gpu'), (2, 'gpu')]


def test_child_accepts_only_complete_administrator_pinned_cache(tmp_path, monkeypatch):
    from service.infrastructure.execution.process import _field_geometry_cache

    names = ('GENERATOR_GEOMETRY_CACHE_DIR', 'GENERATOR_GEOMETRY_CACHE_MANIFEST_SHA256',
             'GENERATOR_GEOMETRY_SOURCE_INDEX', 'GENERATOR_GEOMETRY_SOURCE_AUDIT')
    for name in names:
        monkeypatch.delenv(name, raising=False)
    assert _field_geometry_cache('gpu') is None
    with pytest.raises(ValueError, match='requires field geometry cache'):
        _field_geometry_cache('gpu-fused')
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'manifest.json').write_text('{}')
    index, audit = tmp_path / 'index', tmp_path / 'audit'
    index.write_text('index')
    audit.write_text('audit')
    values = (str(cache), 'a' * 64, str(index), str(audit))
    for name, value in zip(names, values, strict=True):
        monkeypatch.setenv(name, value)
    assert _field_geometry_cache('gpu') == {
        'directory': cache, 'expected_manifest_sha256': 'a' * 64,
        'source_index': index, 'source_audit': audit,
    }
    assert _field_geometry_cache('gpu-fused') == _field_geometry_cache('gpu')
    with pytest.raises(ValueError, match='cache configuration'):
        _field_geometry_cache('cpu')
    monkeypatch.setenv(names[1], 'invalid')
    with pytest.raises(ValueError, match='cache configuration'):
        _field_geometry_cache('gpu')
    monkeypatch.delenv(names[1])
    with pytest.raises(ValueError, match='cache configuration'):
        _field_geometry_cache('gpu')


@pytest.mark.parametrize('backend', ['gpu', 'gpu-fused'])
def test_child_forwards_cache_without_accepting_request_paths(tmp_path, monkeypatch, backend):
    observed = []
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.settings.morphology_directories', lambda: [])
    expected = {'trusted': 'administrator configuration'}
    monkeypatch.setattr('service.infrastructure.execution.process._field_geometry_cache',
                        lambda _backend: expected)
    def execute(_graph, _dirs, *, output, geometry_cache, field_backend, **_options):
        observed.append((geometry_cache, field_backend))
        output.mkdir()
        (output / 'metadata.json').write_text('{}')
    monkeypatch.setattr('service.application.field.field_proxy_execution.execute_field_proxy',
                        execute)
    monkeypatch.setenv('GENERATOR_FIELD_BACKEND', backend)
    run_field_proxy_child(payload(), str(tmp_path / 'output'))
    assert observed == [(expected, backend)]


def test_child_owns_work_files_and_exports_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.settings.morphology_directories', lambda: [])
    def execute(_graph, _dirs, *, field_path, output, progress, **_options):
        field_path.write_text('temporary')
        progress({'phase': 'field', 'done': 1, 'total': 1})
        output.mkdir()
        (output / 'metadata.json').write_text('{}')
        (output / 'network.npz').write_bytes(b'example')
    monkeypatch.setattr('service.application.field.field_proxy_execution.execute_field_proxy',
                        execute)
    run_field_proxy_child(payload(), str(tmp_path / 'output'))
    manifest = json.loads((tmp_path / 'output/manifest.json').read_text())
    assert manifest['kind'] == 'experimental-field-proxy'
    assert {item['name'] for item in manifest['files']} == {'metadata.json', 'network.npz'}
    assert not (tmp_path / 'field-proxy-work').exists()
    assert json.loads((tmp_path / 'progress.json').read_text())['done'] == 1


def test_field_progress_is_bounded():
    assert _valid_progress({'phase': 'field', 'done': 0, 'total': 166700})
    assert _valid_progress({'phase': 'field', 'done': 1000, 'total': 166700})
    assert _valid_progress({'phase': 'field_verification', 'done': 0, 'total': 0})
    assert _valid_progress({'phase': 'network', 'done': 0, 'total': 0})
    assert _valid_progress({'phase': 'network', 'done': 10, 'total': 100})
    assert not _valid_progress({'phase': 'network', 'done': 101, 'total': 100})
    assert not _valid_progress({'phase': 'network', 'done': 1, 'total': 1001})
    assert not _valid_progress({'phase': 'field', 'done': 2, 'total': 1})
    assert not _valid_progress({'phase': 'field', 'done': 1, 'total': 166701})


def test_child_failure_records_error_and_removes_work(tmp_path, monkeypatch):
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.registered_graph',
                        lambda: SimpleNamespace(provenance={'manifest_sha256': 'a' * 64}))
    monkeypatch.setattr('service.settings.morphology_directories', lambda: [])
    def fail(_graph, _dirs, *, field_path, **_options):
        field_path.write_text('partial')
        raise ValueError('invalid geometry')
    monkeypatch.setattr('service.application.field.field_proxy_execution.execute_field_proxy', fail)
    with pytest.raises(ValueError, match='invalid geometry'):
        run_field_proxy_child(payload(), str(tmp_path / 'output'))
    assert not (tmp_path / 'field-proxy-work').exists()
    assert not (tmp_path / 'output/manifest.json').exists()
    assert json.loads((tmp_path / 'output/error.json').read_text())['message'] == 'invalid geometry'
