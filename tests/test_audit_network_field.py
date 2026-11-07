import hashlib
import json

import pytest

from scripts.audit_network_field import audit
from scripts.compute_network_field import compute
from service.infrastructure.connectome.morphology_repository import BASE

CONFIG = dict(source_um=[0, 10, 0], return_um=[50, 10, 0], current_na=10,
              conductivity_s_m=.3, clearance_um=1)


def test_audit_independently_checks_completion_chain_and_order(tmp_path):
    path = tmp_path / 'field.jsonl'
    compute([1, 2], [], path, CONFIG, graph_hash='test')
    result = audit(path, [1, 2], graph_hash='test')
    assert result['complete'] and result['statuses'] == {'source_missing': 2}
    lines = path.read_bytes().splitlines(keepends=True)
    path.write_bytes(b''.join(lines[:2]))
    assert audit(path, [1, 2], graph_hash='test', allow_partial=True)['processed'] == 1
    with pytest.raises(ValueError, match='incomplete'):
        audit(path, [1, 2], graph_hash='test')
    row = json.loads(lines[1])
    row['status'] = 'invalid_geometry_or_field'
    path.write_bytes(lines[0] + (json.dumps(row) + '\n').encode())
    with pytest.raises(ValueError, match='checksum'):
        audit(path, [1, 2], graph_hash='test', allow_partial=True)


def test_stream_callback_receives_only_validated_rows_in_graph_order(tmp_path):
    path = tmp_path / 'field.jsonl'
    compute([1, 2], [], path, CONFIG, graph_hash='test')
    observed = []
    audit(path, [1, 2], graph_hash='test',
          on_row=lambda index, row: observed.append((index, row['body_id'])))
    assert observed == [(0, '1'), (1, '2')]
    lines = path.read_bytes().splitlines(keepends=True)
    row = json.loads(lines[2])
    row['body_id'] = '999'
    path.write_bytes(lines[0] + lines[1] + (json.dumps(row) + '\n').encode())
    observed.clear()
    with pytest.raises(ValueError, match='graph IDs'):
        audit(path, [1, 2], graph_hash='test', on_row=lambda i, row: observed.append(i))
    assert observed == [0]


def test_audit_rejects_wrong_graph_identity(tmp_path):
    path = tmp_path / 'field.jsonl'
    compute([1], [], path, CONFIG, graph_hash='test')
    with pytest.raises(ValueError, match='provenance'):
        audit(path, [1], graph_hash='other')


@pytest.mark.parametrize('interpretation', [None, 'validated excitation'])
def test_audit_rejects_missing_or_misleading_field_interpretation(tmp_path, interpretation):
    path = tmp_path / 'field.jsonl'
    compute([], [], path, CONFIG, graph_hash='test')
    header = json.loads(path.read_text(encoding='utf-8').splitlines()[0])
    if interpretation is None:
        del header['interpretation']
    else:
        header['interpretation'] = interpretation
    # Recompute the empty stream's footer chain: the rejection must come from
    # the semantic provenance check, not merely the checksum.
    chain = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
    footer = {'kind': 'footer', 'neurons': 0, 'chain_sha256': chain}
    path.write_text(json.dumps(header) + '\n' + json.dumps(footer) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='provenance'):
        audit(path, [], graph_hash='test')


def test_audit_rejects_malformed_header_and_status_as_invalid_records(tmp_path):
    path = tmp_path / 'field.jsonl'
    path.write_text('[]\n', encoding='utf-8')
    with pytest.raises(ValueError, match='provenance'):
        audit(path, [1], graph_hash='test', allow_partial=True)
    path.unlink()
    compute([1], [], path, CONFIG, graph_hash='test')
    header = json.loads(path.read_text(encoding='utf-8').splitlines()[0])
    row = {'body_id': '1', 'status': []}
    chain = hashlib.sha256(json.dumps(header, sort_keys=True).encode()).hexdigest()
    canonical = json.dumps(row, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()
    row['chain_sha256'] = hashlib.sha256(bytes.fromhex(chain) + canonical).hexdigest()
    path.write_text(json.dumps(header) + '\n' + json.dumps(row) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='status'):
        audit(path, [1], graph_hash='test', allow_partial=True)


def test_partial_geometry_is_explicit_and_policy_is_part_of_resume_identity(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 125 0 0 1 2\n4 3 250 0 0 1 3\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    path = tmp_path / 'field.jsonl'
    compute([42], [tmp_path], path, CONFIG, graph_hash='test', allow_degenerate=True)
    assert audit(path, [42], graph_hash='test')['statuses'] == {'partial_geometry': 1}
    record = json.loads(path.read_text().splitlines()[1])
    assert record['omitted_zero_length_edges'] == 1 and record['omitted_curvature_vertices'] == 2
    with pytest.raises(ValueError, match='configuration'):
        compute([42], [tmp_path], path, CONFIG, graph_hash='test')


def test_audit_reports_contact_exclusion_without_exposing_paths(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    raw = b'1 1 0 0 0 1 -1\n2 3 1250 0 0 1 1\n'
    (tmp_path / 'raw/42.swc').write_bytes(raw)
    (tmp_path / 'receipts/42.json').write_text(json.dumps({
        'body_id': 42, 'url': BASE + '42.swc', 'sha256': hashlib.sha256(raw).hexdigest(),
    }))
    config = {**CONFIG, 'source_um': [0, 0, 0], 'return_um': [50, 0, 0]}
    path = tmp_path / 'field.jsonl'
    compute([42, 43], [tmp_path], path, config, graph_hash='test')
    result = audit(path, [42, 43], graph_hash='test')
    assert result['failure_categories'] == {'contact_exclusion': 1, 'source_missing': 1}
