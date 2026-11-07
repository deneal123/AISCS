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


def test_audit_rejects_wrong_graph_identity(tmp_path):
    path = tmp_path / 'field.jsonl'
    compute([1], [], path, CONFIG, graph_hash='test')
    with pytest.raises(ValueError, match='provenance'):
        audit(path, [1], graph_hash='other')


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
