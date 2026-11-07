import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.field.field_proxy_preview import field_proxy_preview
from service.infrastructure.execution.process import _file_sha256, _valid_progress, run_field_proxy_child


def payload():
    return {'execution_id': '00000000-0000-0000-0000-000000000001', 'config': {
        'graph_manifest_sha256': 'a' * 64, 'coordinate_frame': 'male-cns-v1.0-native-um',
        'source_um': [0., 0., 0.], 'return_um': [10., 0., 0.], 'current_na': -300.,
        'conductivity_s_m': .3, 'clearance_um': 1., 'gain': 1., 'seed': 1,
        'waveform': [0., 1., 0.], 'allow_partial_geometry': False,
        'allow_missing_curvature': False}}


def test_preview_reports_actual_events_without_fabricating_recording():
    graph = SimpleNamespace(size=3)
    run = {'spike_times_ms': np.array([1, 2, 2]), 'counts': np.array([2, 0, 1]),
           'control_spike_times_ms': np.array([2])}
    provenance = {'excluded_from_direct_field': ['one'], 'excluded_contact_intersections': []}
    preview = field_proxy_preview(graph, run, [0, 1, 0], provenance)
    assert preview['spikes_by_ms'] == [0, 1, 2, 0]
    assert preview['control_spikes_by_ms'] == [0, 0, 1, 0]
    assert preview['active_neurons'] == 2
    assert preview['direct_field_exclusions'] == 1
    assert preview['recording'] is None
    with pytest.raises(ValueError, match='event summary'):
        field_proxy_preview(graph, {**run, 'spike_times_ms': np.array([4])}, [0, 1, 0], provenance)


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
    monkeypatch.setitem(sys.modules, 'service.settings', SimpleNamespace(morphology_directories=lambda: []))
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
    monkeypatch.setattr('service.application.field.field_proxy_execution.execute_field_proxy', execute)
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
