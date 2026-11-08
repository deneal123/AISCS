import hashlib
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import run_field_proxy as runner
from scripts.compute_network_field import compute
from scripts.run_field_proxy import verified_descriptors
from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.fragment_sparse_delta import decode_sparse_delta


@pytest.mark.parametrize('key', ['allow_partial_geometry', 'allow_missing_curvature',
                                'allow_contact_exclusion'])
@pytest.mark.parametrize('value', ['false', 1, None])
def test_exclusion_policies_must_be_explicit_booleans(tmp_path, key, value):
    field = tmp_path / 'not-created.jsonl'
    with pytest.raises(ValueError, match='exclusion policy'):
        verified_descriptors(field, [], 'test', **{key: value})
    assert not field.exists()


@pytest.mark.parametrize('key', ['compute_field', 'allow_partial_geometry',
                                'allow_missing_curvature', 'allow_contact_exclusion'])
def test_execution_rejects_non_boolean_policy_before_computation(tmp_path, key):
    field, output = tmp_path / 'field.jsonl', tmp_path / 'output'
    with pytest.raises(ValueError, match='execution policy'):
        runner.execute_field_proxy(None, [], field_path=field, output=output, configuration={},
                                   gain=1, seed=1, waveform=[0], **{key: 'false'})
    assert not field.exists() and not output.exists()


@pytest.mark.parametrize('invalid', [
    {'waveform': []}, {'waveform': [float('inf')]}, {'waveform': [[0.]]},
    {'gain': float('nan')}, {'gain': True}, {'seed': -1}, {'capture_delta': 'false'},
])
def test_execution_rejects_invalid_network_input_before_field(tmp_path, monkeypatch, invalid):
    from service.application.field import field_proxy_execution

    monkeypatch.setattr(field_proxy_execution, 'compute',
                        lambda *args, **kwargs: pytest.fail('field calculation started'))
    args = dict(field_path=tmp_path / 'field.jsonl', output=tmp_path / 'output',
                configuration={}, gain=1., seed=1, waveform=[0.], compute_field=True)
    with pytest.raises(ValueError, match='experimental field input'):
        runner.execute_field_proxy(SimpleNamespace(provenance={'manifest_sha256': 'test'}),
                                   [], **{**args, **invalid})
    assert not args['field_path'].exists() and not args['output'].exists()


def test_gpu_backend_forwarding_and_invalid_modes(tmp_path, monkeypatch):
    from service.application.field import field_proxy_execution

    calls = []

    def compute_stub(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError('stopped before device execution')

    monkeypatch.setattr(field_proxy_execution, 'compute', compute_stub)
    graph = SimpleNamespace(ids=np.array([42]), size=1, provenance={'manifest_sha256': 'test'})
    args = dict(field_path=tmp_path / 'field.jsonl', output=tmp_path / 'output',
                configuration={}, gain=1., seed=1, waveform=[0.], compute_field=True)
    with pytest.raises(RuntimeError, match='stopped before device'):
        runner.execute_field_proxy(graph, [], **args, field_backend='gpu')
    assert calls[0]['field_backend'] == 'gpu' and calls[0]['workers'] == 1
    with pytest.raises(RuntimeError, match='stopped before device'):
        runner.execute_field_proxy(graph, [], **args, field_backend='gpu', field_workers=2)
    assert calls[1]['field_backend'] == 'gpu' and calls[1]['workers'] == 2
    cache = {'trusted': 'passed through to the field validator'}
    with pytest.raises(RuntimeError, match='stopped before device'):
        runner.execute_field_proxy(graph, [], **args, field_backend='gpu', geometry_cache=cache)
    assert calls[2]['geometry_cache'] is cache
    with pytest.raises(RuntimeError, match='stopped before device'):
        runner.execute_field_proxy(graph, [], **args, field_backend='gpu-fused',
                                   geometry_cache=cache)
    assert calls[3]['field_backend'] == 'gpu-fused' and calls[3]['geometry_cache'] is cache
    for changes in ({'field_backend': 'unknown'}, {'field_backend': 'gpu', 'field_workers': 0},
                    {'field_backend': 'gpu', 'compute_field': False}, {'geometry_cache': cache},
                    {'field_backend': 'gpu-fused'},
                    {'field_backend': 'gpu-fused', 'compute_field': False, 'geometry_cache': cache},
                    {'field_backend': 'gpu', 'compute_field': False, 'geometry_cache': cache}):
        with pytest.raises(ValueError):
            runner.execute_field_proxy(graph, [], **{**args, **changes})
    assert len(calls) == 4 and not args['field_path'].exists() and not args['output'].exists()


def test_cli_fused_requires_all_cache_inputs_before_graph_loading(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'registered_graph', lambda: pytest.fail('graph was loaded'))
    monkeypatch.setattr(sys, 'argv', [
        'run_field_proxy.py', '--field', str(tmp_path / 'field'), '--output', str(tmp_path / 'out'),
        '--gain', '1', '--seed', '1', '--waveform', str(tmp_path / 'waveform.json'),
        '--field-backend', 'gpu-fused', '--compute-field',
        '--source-um', '0', '0', '0', '--return-um', '10', '0', '0',
        '--current-na', '1', '--conductivity-s-m', '.3', '--clearance-um', '1',
    ])
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
    assert not (tmp_path / 'out').exists()


def test_verified_descriptors_rejects_tampering_and_missing_cells(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 250 0 0 1 2\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    field = tmp_path / 'field.jsonl'
    config = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
                  conductivity_s_m=.3, clearance_um=1)
    compute([42], [tmp_path], field, config, graph_hash='test')
    values, provenance = verified_descriptors(field, [42], 'test', expected_configuration=config)
    assert len(values) == 1 and provenance['field_audit']['complete']
    with pytest.raises(ValueError, match='configuration'):
        verified_descriptors(field, [42], 'test',
                             expected_configuration={**config, 'source_um': [1, 10, 0]})
    data = field.read_text().replace('"vertices": 3', '"vertices": 4')
    field.write_text(data)
    with pytest.raises(ValueError, match='checksum'):
        verified_descriptors(field, [42], 'test')
    with pytest.raises(ValueError):
        verified_descriptors(field, [42, 43], 'test')


def test_missing_curvature_requires_explicit_exclusion(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    field = tmp_path / 'field.jsonl'
    config = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
                  conductivity_s_m=.3, clearance_um=1)
    compute([42], [tmp_path], field, config, graph_hash='test')
    with pytest.raises(ValueError):
        verified_descriptors(field, [42], 'test')
    values, provenance = verified_descriptors(field, [42], 'test', allow_missing_curvature=True)
    assert values.tolist() == [0.]
    assert provenance['excluded_from_direct_field'] == ['42']


def test_verified_descriptors_rejects_file_changed_during_stream(tmp_path, monkeypatch):
    from service.infrastructure.stimulation import field_summary_verified

    field = tmp_path / 'field.jsonl'
    compute([], [], field, dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
                               conductivity_s_m=.3, clearance_um=1), graph_hash='test')
    hashes = iter(['a' * 64, 'b' * 64])
    monkeypatch.setattr(field_summary_verified, 'digest', lambda _path: next(hashes))
    with pytest.raises(ValueError, match='changed while reading'):
        verified_descriptors(field, [], 'test')


def test_contact_intersection_requires_explicit_recorded_exclusion(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 1250 0 0 1 1\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    field = tmp_path / 'field.jsonl'
    config = dict(source_um=[0, 0, 0], return_um=[50, 0, 0], current_na=10,
                  conductivity_s_m=.3, clearance_um=1)
    compute([42], [tmp_path], field, config, graph_hash='test')
    with pytest.raises(ValueError, match='failed geometry'):
        verified_descriptors(field, [42], 'test')
    values, provenance = verified_descriptors(field, [42], 'test', allow_contact_exclusion=True)
    assert values.tolist() == [0.]
    assert provenance['excluded_contact_intersections'] == ['42']


def test_cli_computes_field_and_rejects_moved_contact(tmp_path, monkeypatch):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 250 0 0 1 2\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    graph = SimpleNamespace(ids=np.array([42]), size=1, ptr=np.array([0, 0]),
        posts=np.array([], np.int32), counts=np.array([], np.int32), signs=np.array([1], np.int8),
        provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr(runner, 'registered_graph', lambda: graph)
    monkeypatch.setattr(runner, 'morphology_directories', lambda: [tmp_path])
    waveform = tmp_path / 'wave.json'
    waveform.write_text('[0, 1, 0]')
    args = ['run_field_proxy', '--field', str(tmp_path / 'field.jsonl'), '--compute-field',
            '--capture-delta',
            '--output', str(tmp_path / 'result'), '--gain', '1', '--seed', '1',
            '--waveform', str(waveform), '--source-um', '0', '10', '0',
            '--return-um', '50', '10', '0', '--current-na', '10',
            '--conductivity-s-m', '.3', '--clearance-um', '1']
    monkeypatch.setattr(sys, 'argv', args)
    runner.main()
    metadata = json.loads((tmp_path / 'result/metadata.json').read_text())
    assert metadata['field']['field_audit']['configuration']['source_um'] == [0, 10, 0]
    assert len(metadata['kernel_source_sha256']) == 64
    assert metadata['time_step_ms'] == 1.0 and metadata['network_weight_gain'] == .075
    assert metadata['field_execution'] == {
        'computation_requested': True, 'requested_backend': 'cpu',
        'requested_preparation_workers': 1,
    }
    binary = (tmp_path / 'result/network-events.bin').read_bytes()
    assert hashlib.sha256(binary).hexdigest() == metadata['event_sha256']
    assert metadata['event_description']['binary']['bytes'] == len(binary)
    delta = decode_sparse_delta((tmp_path / 'result/state-delta.bin').read_bytes(),
        graph=graph, source_ids=[], duration_ms=3,
        configuration_sha256=metadata['state_delta']['configuration_sha256'])
    assert delta['status'] == 'recorded'
    assert (tmp_path / 'result/state-response.bin').read_bytes().startswith(b'FRS2')
    assert len(metadata['state_delta']['sampled_sha256']) == 64
    progress = []
    reused = runner.execute_field_proxy(graph, [tmp_path], field_path=tmp_path / 'field.jsonl',
        output=tmp_path / 'second', configuration=metadata['field']['field_audit']['configuration'],
        gain=1., seed=1, waveform=[0, 1, 0], progress=progress.append)
    assert reused['field_execution'] == {'computation_requested': False, 'requested_backend': None,
                                         'requested_preparation_workers': None}
    assert progress[0]['phase'] == 'field_verification'
    assert [item['done'] for item in progress[1:]] == [0, 1, 2, 3]
    assert all(item['phase'] == 'network' and item['total'] == 3 for item in progress[1:])
    progress.clear()
    runner.execute_field_proxy(graph, [tmp_path], field_path=tmp_path / 'new-field.jsonl',
        output=tmp_path / 'third', configuration=metadata['field']['field_audit']['configuration'],
        gain=1., seed=1, waveform=[0, 1, 0], compute_field=True, progress=progress.append)
    assert progress[0] == {'phase': 'field', 'done': 0, 'total': 1}
    verified = next(i for i, item in enumerate(progress) if item['phase'] == 'field_verification')
    assert [item['done'] for item in progress[verified + 1:]] == [0, 1, 2, 3]
    moved = args.copy()
    moved[moved.index('--output') + 1] = str(tmp_path / 'moved')
    moved[moved.index('--source-um') + 1] = '1'
    monkeypatch.setattr(sys, 'argv', moved)
    with pytest.raises(ValueError, match='different provenance or configuration'):
        runner.main()
