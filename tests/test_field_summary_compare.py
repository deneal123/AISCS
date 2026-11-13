import hashlib
import json

import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.field.summary_compare import compare
from service.infrastructure.stimulation.field.summary_compute import compute

CONFIG = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
              conductivity_s_m=.3, clearance_um=1)


@pytest.fixture
def fields(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 250 0 0 1 2\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    first, second = tmp_path / 'first.jsonl', tmp_path / 'second.jsonl'
    compute([42], [tmp_path], first, CONFIG, graph_hash='test')
    second.write_bytes(first.read_bytes())
    return first, second


def rewrite(path, change):
    header, row, footer = map(json.loads, path.read_text().splitlines())
    row.pop('chain_sha256')
    change(header, row)
    chain = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
    canonical = json.dumps(row, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    row['chain_sha256'] = hashlib.sha256(bytes.fromhex(chain) + canonical).hexdigest()
    footer['chain_sha256'] = row['chain_sha256']
    path.write_text('\n'.join(json.dumps(item) for item in (header, row, footer)) + '\n')


def test_compare_checks_extrema_and_reports_metadata_mismatch(fields):
    first, second = fields
    assert compare(first, second, [42], graph_hash='test')['equal_within_tolerance']
    rewrite(second, lambda header, row: row.update(max_abs_curvature_signed_mv_per_um2=1.0))
    result = compare(first, second, [42], graph_hash='test')
    assert result['mismatch_count'] == 1
    assert result['nonidentical_extrema'] == 1
    assert result['max_symmetric_relative_delta'] > 0
    assert result['examples'][0]['body_id'] == '42'
    assert result['examples'][0]['metadata_equal']
    rewrite(second, lambda header, row: row.update(source_sha256='a' * 64))
    assert not compare(first, second, [42], graph_hash='test')['examples'][0]['metadata_equal']


def test_compare_requires_complete_matching_configuration_and_integrity(fields):
    first, second = fields
    rewrite(second, lambda header, row: header['configuration'].update(current_na=11))
    with pytest.raises(ValueError, match='configurations'):
        compare(first, second, [42], graph_hash='test')
    second.write_bytes(first.read_bytes().splitlines(keepends=True)[0])
    with pytest.raises(ValueError, match='incomplete'):
        compare(first, second, [42], graph_hash='test')
    with pytest.raises(ValueError, match='tolerance'):
        compare(first, first, [42], graph_hash='test', rel_tol=float('nan'))


def test_compare_rejects_a_file_changed_while_reading(fields, monkeypatch):
    from service.infrastructure.stimulation.field import summary_compare as field_summary_compare

    first, second = fields
    actual = field_summary_compare._sha256
    calls = 0

    def changing_digest(path):
        nonlocal calls
        calls += 1
        return 'different' if calls == 4 else actual(path)

    monkeypatch.setattr(field_summary_compare, '_sha256', changing_digest)
    with pytest.raises(ValueError, match='changed during comparison'):
        compare(first, second, [42], graph_hash='test')
