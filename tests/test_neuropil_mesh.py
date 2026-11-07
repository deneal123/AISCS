import hashlib
import json
import struct

import numpy as np
import pytest

from scripts.audit_neuropil import audit
from scripts.export_neuropil_lod import cluster_surface, export
from service.infrastructure.connectome.neuropil_mesh import decode_legacy_mesh


def fixture():
    vertices = np.array([[1000, 2000, 3000], [2000, 2000, 3000], [1000, 3000, 3000]],
                        dtype="<f4")
    faces = np.array([[0, 1, 2]], dtype="<u4")
    return struct.pack("<I", len(vertices)) + vertices.tobytes() + faces.tobytes()


def test_source_mesh_preserves_vertices_faces_and_units():
    raw = fixture()
    result = decode_legacy_mesh(raw, expected_sha256=hashlib.sha256(raw).hexdigest())
    np.testing.assert_array_equal(result["vertices_um"], [[1, 2, 3], [2, 2, 3], [1, 3, 3]])
    np.testing.assert_array_equal(result["faces"], [[0, 1, 2]])


def test_corrupt_checksum_layout_and_indices_are_rejected():
    raw = fixture()
    with pytest.raises(ValueError, match="checksum"):
        decode_legacy_mesh(raw, expected_sha256="0" * 64)
    for invalid in (raw[:-1], raw[:-4] + struct.pack("<I", 9),
                    struct.pack("<I", 2**32 - 1) + raw[4:]):
        with pytest.raises(ValueError):
            decode_legacy_mesh(invalid, expected_sha256=hashlib.sha256(invalid).hexdigest())


def test_inventory_rejects_corrupt_files_and_duplicate_ids(tmp_path):
    raw = fixture()
    folder = tmp_path / "fullbrain-roi-v4"
    folder.mkdir()
    (folder / "1.ngmesh").write_bytes(raw)
    record = {"dataset": "fullbrain-roi-v4", "id": "1", "label": "AL(L)",
              "file": "fullbrain-roi-v4/1.ngmesh", "sha256": hashlib.sha256(raw).hexdigest(),
              "fragments": [{"bytes": len(raw), "etag": hashlib.md5(raw).hexdigest()}]}
    receipt = tmp_path / "inventory.json"
    receipt.write_text(json.dumps([record]))
    assert audit(tmp_path)["regions"] == 1
    receipt.write_text(json.dumps([record, record]))
    with pytest.raises(ValueError, match="inventory"):
        audit(tmp_path)
    receipt.write_text(json.dumps([record]))
    (folder / "1.ngmesh").write_bytes(raw[:-1])
    with pytest.raises(ValueError, match="MD5"):
        audit(tmp_path)


def test_visual_lod_is_deterministic_and_rejects_missing_geometry():
    vertices = np.array([[0, 0, 0], [.1, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=float)
    faces = np.array([[0, 2, 3], [1, 2, 3], [0, 1, 2]], dtype=int)
    a, f, error = cluster_surface(vertices, faces, 1)
    b, g, second_error = cluster_surface(vertices, faces, 1)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(f, g)
    assert len(f) == 1 and error == second_error and error <= np.sqrt(3)
    with pytest.raises(ValueError, match="no triangles"):
        cluster_surface(vertices[:3], np.array([[0, 1, 1]]), 1)


def test_visual_export_refuses_invalid_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        export(tmp_path, tmp_path / "result", 3)
