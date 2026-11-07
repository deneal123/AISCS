import hashlib
import json

import pytest

from scripts.compute_network_field import compute
from scripts.recover_field_prefix import recover
from tests.test_compute_network_field import CONFIG


def test_recovery_preserves_original_and_resumes_verified_prefix(tmp_path):
    source, recovered = tmp_path / 'source.jsonl', tmp_path / 'recovered.jsonl'
    ids = [1, 2, 3]
    compute(ids, [], source, CONFIG, graph_hash='graph')
    complete = source.read_bytes()
    lines = complete.splitlines(keepends=True)
    interrupted = lines[0] + lines[1] + lines[2][:-5]
    source.write_bytes(interrupted)
    result = recover(source, recovered, ids, graph_hash='graph')
    assert result['processed'] == 1 and result['expected'] == 3
    assert result['source_sha256'] == hashlib.sha256(interrupted).hexdigest()
    assert result['prefix_sha256'] == hashlib.sha256(lines[0] + lines[1]).hexdigest()
    assert source.read_bytes() == interrupted
    assert compute(ids, [], recovered, CONFIG, graph_hash='graph') == 3
    assert recovered.read_bytes() == complete


def test_recovery_rejects_corruption_completed_source_and_existing_output(tmp_path):
    source, target = tmp_path / 'source.jsonl', tmp_path / 'target.jsonl'
    compute([1], [], source, CONFIG, graph_hash='graph')
    complete = source.read_bytes()
    with pytest.raises(ValueError, match='no incomplete'):
        recover(source, target, [1], graph_hash='graph')
    source.write_bytes(complete + b'incomplete')
    with pytest.raises(ValueError, match='Complete field'):
        recover(source, target, [1], graph_hash='graph')
    lines = complete.splitlines(keepends=True)
    row = json.loads(lines[1])
    row['status'] = 'invalid_geometry_or_field'
    source.write_bytes(lines[0] + (json.dumps(row) + '\n').encode() + b'partial')
    with pytest.raises(ValueError, match='checksum'):
        recover(source, target, [1], graph_hash='graph')
    assert not target.exists()
    target.write_text('untouched')
    with pytest.raises(ValueError, match='existing'):
        recover(source, target, [1], graph_hash='graph')
    assert target.read_text() == 'untouched'
