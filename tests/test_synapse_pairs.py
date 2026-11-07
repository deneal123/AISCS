import hashlib

import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from service.infrastructure.connectome.synapse_pairs import FIELDS, extract_pairs


def write_table(path):
    rows = [
        dict(body_pre=1, body_post=2, x_pre=10, y_pre=11, z_pre=12,
             x_post=13, y_post=14, z_post=15),
        dict(body_pre=1, body_post=3, x_pre=20, y_pre=21, z_pre=22,
             x_post=23, y_post=24, z_post=25),
        dict(body_pre=3, body_post=1, x_pre=30, y_pre=31, z_pre=32,
             x_post=33, y_post=34, z_post=35),
    ]
    table = pa.Table.from_pylist(rows).select(FIELDS)
    with pa.OSFile(str(path), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table, max_chunksize=1)
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def test_scan_keeps_direction_coordinates_total_and_truncation(tmp_path):
    source = tmp_path / 'pairs.feather'
    digest = write_table(source)
    result = extract_pairs(source, 1, digest, direction='outgoing', limit=1)
    assert result['total'] == 2 and result['returned'] == 1 and result['truncated']
    assert result['pairs'][0]['body_post'] == 2 and result['pairs'][0]['x_pre'] == 10
    incoming = extract_pairs(source, 1, digest, direction='incoming')
    assert incoming['total'] == 1 and incoming['pairs'][0]['body_pre'] == 3
    assert incoming['coordinate_frame'] == 'male-cns-v1.0-native-8nm'
    assert extract_pairs(source, 8, digest, direction='incoming')['pairs'] == []


def test_scan_rejects_invalid_checksum_and_parameters(tmp_path):
    source = tmp_path / 'pairs.feather'
    digest = write_table(source)
    with pytest.raises(ValueError, match='checksum mismatch'):
        extract_pairs(source, 1, '0' * 32, direction='incoming')
    for kwargs in ({'body_id': True}, {'direction': 'both'}, {'limit': 0}, {'limit': True}):
        params = dict(body_id=1, direction='incoming', limit=1)
        params.update(kwargs)
        with pytest.raises(ValueError):
            extract_pairs(source, expected_md5=digest, **params)
