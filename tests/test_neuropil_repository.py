import hashlib
import json

import pytest

from service.infrastructure.connectome.dataset import MANIFEST_SHA256
from service.infrastructure.connectome.neuropil_repository import neuropil_chunk, neuropil_manifest


def make_generation(root):
    raw = b"test gzip"
    meshes = []
    for dataset, count in (("fullbrain-roi-v4", 90), ("malecns-vnc-neuropil-roi-v0", 24)):
        for i in range(1, count + 1):
            name = f"{dataset}-{i}.bin.gz"
            meshes.append({"dataset": dataset, "id": str(i), "file": name, "label": "region",
                           "sha256": hashlib.sha256(raw).hexdigest(), "source_sha256": "a" * 64,
                           "bytes": len(raw), "vertices": 3, "triangles": 1,
                           "max_vertex_displacement_um": 0})
    (root / meshes[0]["file"]).write_bytes(raw)
    manifest = {"dataset_id": "male-cns:v1.0-annotated-nonglial",
                "manifest_sha256": MANIFEST_SHA256,
                "source_frame": "MaleCNS native unmirrored EM", "units": "um",
                "method": "vertex-grid-visual-lod-v1", "grid_um": 3, "meshes": meshes}
    (root / "manifest.json").write_text(json.dumps(manifest))
    return manifest, raw


def test_manifest_and_chunk_reject_missing_duplicate_and_corrupt_data(tmp_path):
    manifest, raw = make_generation(tmp_path)
    assert len(neuropil_manifest(tmp_path)["meshes"]) == 114
    assert neuropil_chunk(tmp_path, manifest["meshes"][0]["file"]) == raw
    with pytest.raises(FileNotFoundError):
        neuropil_chunk(tmp_path, "../invalid")
    (tmp_path / manifest["meshes"][0]["file"]).write_bytes(b"corrupt!!")
    with pytest.raises(ValueError, match="checksum"):
        neuropil_chunk(tmp_path, manifest["meshes"][0]["file"])
    manifest["meshes"][-1] = manifest["meshes"][0]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="mesh"):
        neuropil_manifest(tmp_path)
