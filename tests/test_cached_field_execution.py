import json

import pytest

from service.infrastructure.stimulation.field_summary_audit import audit
from service.infrastructure.stimulation.field_summary_compute import compute
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
