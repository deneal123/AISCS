import hashlib
import json

import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.field import fused_compare as fused_field_compare
from service.infrastructure.stimulation.field.summary_compute import compute
from tests.test_cached_field_execution import cache_options
from tests.test_packed_geometry_cache import build
from tests.test_packed_geometry_cache import fixture as geometry_case  # noqa: F401
from tests.test_packed_geometry_chunk import sources  # noqa: F401
from tests.test_packed_geometry_index import index  # noqa: F401

CONFIG = {'source_um': [0., 10., 0.], 'return_um': [50., 10., 0.], 'current_na': 100.,
          'conductivity_s_m': .3, 'clearance_um': 1.}


def test_fused_comparison_covers_all_cells_and_checks_mismatches(
    geometry_case, monkeypatch,  # noqa: F811
):
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    args = {'geometry_cache': cache_options(geometry_case, manifest), 'graph_ids': [10, 20],
            'graph_sha256': geometry_case['graph'], 'configuration': CONFIG}
    updates = []
    report = fused_field_compare.compare_cache(**args, progress=lambda done, total: updates.append(
        (done, total)))
    assert updates == [(1, 2), (2, 2)]
    assert report['neurons'] == 2 and report['mismatches'] == 0
    assert report['device']['name'] and report['cache_manifest_sha256'] == manifest
    original = fused_field_compare.experimental_summaries

    def wrong(*args, **kwargs):
        rows, fallbacks = original(*args, **kwargs)
        rows[0]['body_id'] = 'incorrect'
        return rows, fallbacks

    monkeypatch.setattr(fused_field_compare, 'experimental_summaries', wrong)
    report = fused_field_compare.compare_cache(**args)
    assert report['mismatches'] == 2
    assert [item['body_id'] for item in report['examples']] == ['10', '20']


def test_fused_comparison_rejects_incomplete_options():
    with pytest.raises(ValueError, match='configuration'):
        fused_field_compare.compare_cache(geometry_cache={}, graph_ids=[], graph_sha256='a' * 64,
                                         configuration={})


def test_fused_comparison_accepts_matching_cpu_reference(geometry_case, tmp_path):  # noqa: F811
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    field = tmp_path / 'cpu.jsonl'
    compute([10, 20], [geometry_case['source']], field, CONFIG,
            graph_hash=geometry_case['graph'])
    report = fused_field_compare.compare_cache(
        geometry_cache=cache_options(geometry_case, manifest), graph_ids=[10, 20],
        graph_sha256=geometry_case['graph'], configuration=CONFIG, reference_field=field)
    assert report['mismatches'] == report['reference_mismatches'] == 0
    assert len(report['reference_field_sha256']) == 64
    with pytest.raises(ValueError, match='Reference field configuration'):
        fused_field_compare.compare_cache(
            geometry_cache=cache_options(geometry_case, manifest), graph_ids=[10, 20],
            graph_sha256=geometry_case['graph'], configuration={**CONFIG, 'current_na': 10.},
            reference_field=field)


def test_fused_comparison_reports_reference_mismatch_and_mutation(
    geometry_case, tmp_path, monkeypatch,  # noqa: F811
):
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    alternate = tmp_path / 'alternate'
    (alternate / 'raw').mkdir(parents=True)
    (alternate / 'receipts').mkdir()
    for body in (10, 20):
        raw = (geometry_case['source'] / f'raw/{body}.swc').read_bytes()
        if body == 10:
            raw = raw.replace(b'100.5', b'101.5')
        (alternate / f'raw/{body}.swc').write_bytes(raw)
        (alternate / f'receipts/{body}.json').write_text(json.dumps({
            'body_id': body, 'url': BASE + f'{body}.swc',
            'sha256': hashlib.sha256(raw).hexdigest(),
        }))
    field = tmp_path / 'alternate.jsonl'
    compute([10, 20], [alternate], field, CONFIG, graph_hash=geometry_case['graph'])
    options = {'geometry_cache': cache_options(geometry_case, manifest), 'graph_ids': [10, 20],
               'graph_sha256': geometry_case['graph'], 'configuration': CONFIG,
               'reference_field': field}
    report = fused_field_compare.compare_cache(**options)
    assert report['mismatches'] == 0 and report['reference_mismatches'] == 1
    assert report['reference_examples'][0]['body_id'] == '10'
    original_audit = fused_field_compare.audit_field

    def changed_after_audit(path, *args, **kwargs):
        result = original_audit(path, *args, **kwargs)
        with path.open('a') as stream:
            stream.write('\n')
        return result

    monkeypatch.setattr(fused_field_compare, 'audit_field', changed_after_audit)
    with pytest.raises(ValueError, match='Reference field changed'):
        fused_field_compare.compare_cache(**options)


def test_fused_comparison_rejects_source_changed_during_run(
    geometry_case, monkeypatch,  # noqa: F811
):
    from numba import cuda

    if not cuda.is_available():
        pytest.skip('CUDA toolkit and device are not available')
    manifest = build(geometry_case)
    hashes = iter(['a' * 64] * 4 + ['b' * 64] * 4)
    monkeypatch.setattr(fused_field_compare, 'digest', lambda _path: next(hashes))
    with pytest.raises(ValueError, match='operator changed'):
        fused_field_compare.compare_cache(
            geometry_cache=cache_options(geometry_case, manifest), graph_ids=[10, 20],
            graph_sha256=geometry_case['graph'], configuration=CONFIG)
