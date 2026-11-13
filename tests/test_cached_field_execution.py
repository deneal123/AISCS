import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.field.proxy_execution import execute_field_proxy
from service.infrastructure.stimulation.field.summary_audit import audit
from service.infrastructure.stimulation.field.summary_compute import compute
from tests.test_packed_geometry_cache import build
from tests.test_packed_geometry_cache import fixture as geometry_case  # noqa: F401
from tests.test_packed_geometry_chunk import sources  # noqa: F401
from tests.test_packed_geometry_index import index  # noqa: F401

CONFIG = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
              conductivity_s_m=.3, clearance_um=1)


def cache_options(case, manifest):
    return {'directory': case['directory'], 'expected_manifest_sha256': manifest,
            'source_index': case['database'], 'source_audit': case['audit']}


def test_cached_execution_requires_gpu_and_complete_config(geometry_case, tmp_path):  # noqa: F811
    output = tmp_path / 'out.jsonl'
    manifest = build(geometry_case)
    with pytest.raises(ValueError, match='GPU geometry cache'):
        compute([10, 20], [], output, CONFIG, graph_hash=geometry_case['graph'],
                geometry_cache=cache_options(geometry_case, manifest))
    assert not output.exists()


@pytest.mark.parametrize('identity', ['x' * 64, 'a' * 64])
def test_audit_rejects_invalid_cache_provenance(tmp_path, identity):
    output = tmp_path / 'out.jsonl'
    compute([1], [], output, CONFIG, graph_hash='graph')
    lines = output.read_text().splitlines()
    header = json.loads(lines[0])
    header['geometry_cache_manifest_sha256'] = identity
    lines[0] = json.dumps(header)
    output.write_text('\n'.join(lines) + '\n')
    with pytest.raises(ValueError, match='geometry cache provenance'):
        audit(output, [1], graph_hash='graph')


def test_real_gpu_cache_matches_direct_and_resume(geometry_case, tmp_path):  # noqa: F811
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    options = cache_options(geometry_case, manifest)
    direct, cached = tmp_path / 'direct.jsonl', tmp_path / 'cached.jsonl'
    args = {'graph_hash': geometry_case['graph'], 'field_backend': 'gpu'}
    assert compute([10, 20], [geometry_case['source']], direct, CONFIG, **args) == 2
    assert compute([10, 20], [], cached, CONFIG, geometry_cache=options, **args) == 2
    def records(path):
        return [json.loads(line) for line in path.read_text().splitlines()]
    direct_rows, cached_rows = records(direct), records(cached)
    assert cached_rows[0]['geometry_cache_manifest_sha256'] == manifest
    for a, b in zip(direct_rows[1:-1], cached_rows[1:-1], strict=True):
        a.pop('chain_sha256')
        b.pop('chain_sha256')
        assert a == b
    assert audit(cached, [10, 20], graph_hash=geometry_case['graph'])['complete']
    original = cached.read_bytes()
    cached.write_bytes(b''.join(original.splitlines(keepends=True)[:2]))
    assert compute([10, 20], [], cached, CONFIG, geometry_cache=options, **args) == 2
    assert cached.read_bytes() == original

    # No completion footer may be published if a later cache chunk is corrupt.
    broken = geometry_case['directory'] / 'chunk-000001.bin'
    raw = bytearray(broken.read_bytes())
    raw[0] ^= 1
    broken.write_bytes(raw)
    partial = tmp_path / 'partial.jsonl'
    with pytest.raises(ValueError, match='geometry checksum'):
        compute([10, 20], [], partial, CONFIG, geometry_cache=options, **args)
    assert all(row.get('kind') != 'footer' for row in records(partial))


@pytest.mark.parametrize('field_backend', ['gpu', 'gpu-fused'])
def test_cached_gpu_field_feeds_proxy_and_records_its_source(
    geometry_case, tmp_path, field_backend,  # noqa: F811
):
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    graph = SimpleNamespace(ids=np.array([10, 20]), size=2, ptr=np.array([0, 0, 0]),
        posts=np.array([], np.int32), counts=np.array([], np.int32),
        signs=np.array([1, 1], np.int8), provenance={'manifest_sha256': geometry_case['graph']})
    field_path, output = tmp_path / 'field.jsonl', tmp_path / 'result'
    execute_field_proxy(graph, [], field_path=field_path, output=output, configuration=CONFIG,
                        gain=1., seed=1, waveform=[0., 1., 0.], compute_field=True,
                        allow_missing_curvature=True, field_backend=field_backend,
                        geometry_cache=cache_options(geometry_case, manifest))
    header = json.loads(field_path.read_text().splitlines()[0])
    assert header['geometry_cache_manifest_sha256'] == manifest
    assert (output / 'metadata.json').is_file()
    metadata = json.loads((output / 'metadata.json').read_text())
    assert metadata['field']['field_audit']['geometry_cache_manifest_sha256'] == manifest
    assert metadata['field_execution']['requested_backend'] == field_backend
    assert json.loads((output / 'field-proxy-preview.json').read_text())['recording'] is None


def test_cached_field_failure_closes_background_reader(geometry_case, tmp_path):  # noqa: F811
    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    output = tmp_path / 'partial.jsonl'
    def reject(_row):
        raise ValueError('row rejected')
    with pytest.raises(ValueError, match='row rejected'):
        compute([10, 20], [], output, CONFIG, graph_hash=geometry_case['graph'],
                field_backend='gpu', geometry_cache=cache_options(geometry_case, manifest),
                check_row=reject)
    assert all(not thread.name.startswith('geometry-read') for thread in threading.enumerate())
    assert all(json.loads(line).get('kind') != 'footer' for line in output.read_text().splitlines())


def test_fused_backend_groups_cached_entries_and_resumes(
    geometry_case, tmp_path, monkeypatch,  # noqa: F811
):
    from types import SimpleNamespace

    from service.infrastructure.stimulation import experimental_fused_gpu, point_field_gpu

    manifest = build(geometry_case)
    device = SimpleNamespace(name=b'test-device', compute_capability=(8, 6))
    cuda = SimpleNamespace(get_current_device=lambda: device,
                           runtime=SimpleNamespace(get_version=lambda: (12, 9)))
    monkeypatch.setattr(point_field_gpu, '_kernel', lambda: (cuda, None))
    batches = []
    def summaries(entries, **_kwargs):
        batches.append([entry['skeleton']['body_id'] for entry in entries])
        return [{'body_id': entry['skeleton']['body_id'], 'status': 'source_missing'}
                for entry in entries], 0
    monkeypatch.setattr(experimental_fused_gpu, 'experimental_summaries', summaries)
    output = tmp_path / 'fused.jsonl'
    args = {'graph_hash': geometry_case['graph'], 'field_backend': 'gpu-fused',
            'geometry_cache': cache_options(geometry_case, manifest)}
    assert compute([10, 20], [], output, CONFIG, **args) == 2
    assert batches == [['10', '20']]
    original = output.read_bytes()
    assert json.loads(original.splitlines()[0])['field_backend'] == 'gpu-fused'
    assert audit(output, [10, 20], graph_hash=geometry_case['graph'])['complete']
    output.write_bytes(b''.join(original.splitlines(keepends=True)[:2]))
    batches.clear()
    assert compute([10, 20], [], output, CONFIG, **args) == 2
    assert batches == [['20']]
    assert output.read_bytes() == original


def test_fused_gpu_complete_cache_matches_cpu_and_resumes(geometry_case, tmp_path):  # noqa: F811
    from service.infrastructure.stimulation.field.summary_compare import compare

    cuda = pytest.importorskip('numba.cuda')
    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    ids = [10, 20]
    reference, candidate = tmp_path / 'cpu.jsonl', tmp_path / 'fused.jsonl'
    assert compute(ids, [geometry_case['source']], reference, CONFIG,
                   graph_hash=geometry_case['graph']) == 2
    options = {'graph_hash': geometry_case['graph'], 'field_backend': 'gpu-fused',
               'geometry_cache': cache_options(geometry_case, manifest)}
    assert compute(ids, [], candidate, CONFIG, **options) == 2
    comparison = compare(reference, candidate, ids, graph_hash=geometry_case['graph'])
    assert comparison['equal_within_tolerance']
    original = candidate.read_bytes()
    candidate.write_bytes(b''.join(original.splitlines(keepends=True)[:2]))
    assert compute(ids, [], candidate, CONFIG, **options) == 2
    assert candidate.read_bytes() == original


def test_fused_gpu_failure_does_not_publish_success(
    geometry_case, tmp_path, monkeypatch,  # noqa: F811
):
    from types import SimpleNamespace

    from service.infrastructure.stimulation import experimental_fused_gpu, point_field_gpu

    manifest = build(geometry_case)
    device = SimpleNamespace(name=b'test-device', compute_capability=(8, 6))
    cuda = SimpleNamespace(get_current_device=lambda: device,
                           runtime=SimpleNamespace(get_version=lambda: (12, 9)))
    monkeypatch.setattr(point_field_gpu, '_kernel', lambda: (cuda, None))
    def fail(*_args, **_kwargs):
        raise RuntimeError('GPU calculation failed')
    monkeypatch.setattr(experimental_fused_gpu, 'experimental_summaries', fail)
    output = tmp_path / 'failed.jsonl'
    with pytest.raises(RuntimeError, match='GPU calculation failed'):
        compute([10, 20], [], output, CONFIG, graph_hash=geometry_case['graph'],
                field_backend='gpu-fused', geometry_cache=cache_options(geometry_case, manifest))
    assert all(json.loads(line).get('kind') != 'footer' for line in output.read_text().splitlines())
    assert all(not t.name.startswith('geometry-read') for t in threading.enumerate())
