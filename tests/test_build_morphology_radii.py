import hashlib
import json
import sqlite3

import pytest

from scripts.audit_morphology_radii import audit as audit_radii
from scripts.build_morphology_radii import build, max_swc_radius_um


@pytest.mark.parametrize("text", ["", "1 1 0 0 0 -1 -1", "1 1 0 0 0 nan -1", "1 2"])
def test_invalid_radius_source_is_rejected(text):
    with pytest.raises(ValueError):
        max_swc_radius_um(text)


def test_maximum_radius_uses_all_vertices_and_native_units():
    swc = "# comment\n1 1 0 0 0 20 -1\n2 3 10 0 0 125 1\n"
    assert max_swc_radius_um(swc) == pytest.approx(1.)


def test_resumable_radius_index_binds_the_audited_source(tmp_path, monkeypatch):
    source, output = tmp_path / "bounds.sqlite", tmp_path / "radii.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE bounds (body_id INTEGER, status TEXT, sha256 TEXT)")
        db.executemany("INSERT INTO bounds VALUES (?, 'ok', ?)", [(1, 'a' * 64), (2, 'b' * 64)])
    audit = tmp_path / 'audit.json'
    audit.write_text(json.dumps({'format': 'malecns-bounds-audit-v1', 'verified': 2,
                                 'index_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                                 'graph_sha256': 'graph'}), encoding='utf8')
    seen = []

    def read(body, _directories, *, expected_sha256):
        seen.append((body, expected_sha256))
        return {'swc': f'1 1 0 0 0 {body * 125} -1\n'}

    monkeypatch.setattr('scripts.build_morphology_radii.read_skeleton', read)
    monkeypatch.setattr('scripts.audit_morphology_radii.read_skeleton', read)
    assert build(source, audit, output, [], limit=1)['indexed'] == 1
    assert build(source, audit, output, []) == {'indexed': 2, 'expected': 2}
    assert seen == [(1, 'a' * 64), (2, 'b' * 64)]
    assert audit_radii(source, audit, output, [], limit=1) == {'partial': 1, 'expected': 2}
    result = audit_radii(source, audit, output, [])
    assert result['verified'] == 2 and result['format'] == 'malecns-radius-audit-v1'
    with sqlite3.connect(output) as db:
        assert db.execute('SELECT body_id, radius_um FROM radii ORDER BY ordinal').fetchall() == [
            (1, 1.), (2, 2.)
        ]
        original = db.execute(
            "SELECT value FROM metadata WHERE key='algorithm_sha256'"
        ).fetchone()[0]
        db.execute("UPDATE metadata SET value='invalid' WHERE key='algorithm_sha256'")
    with pytest.raises(ValueError, match='metadata'):
        audit_radii(source, audit, output, [])
    with sqlite3.connect(output) as db:
        db.execute("UPDATE metadata SET value=? WHERE key='algorithm_sha256'", (original,))
        db.execute('UPDATE radii SET radius_um=0.5 WHERE body_id=1')
    with pytest.raises(ValueError, match='differs from source'):
        audit_radii(source, audit, output, [])
    with source.open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='audit mismatch'):
        build(source, audit, output, [])
