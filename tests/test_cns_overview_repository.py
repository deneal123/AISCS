import hashlib
import json

import pytest

from service.infrastructure.connectome.dataset import MANIFEST_SHA256
from service.infrastructure.connectome.overview_repository import overview_chunk, overview_manifest


def test_only_registered_complete_manifest_and_verified_chunks_are_served(tmp_path):
    raw = b"compressed-data"
    chunks = []
    for offset in range(0, 166700, 10000):
        count = min(10000, 166700 - offset)
        name = f"overview-{offset:06d}.bin.gz"
        chunks.append(
            {
                "file": name,
                "start": offset,
                "cells": count,
                "cells_with_edges": count,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    doc = {
        "manifest_sha256": MANIFEST_SHA256,
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "method": "evenly-sampled-original-swc-edges-v1",
        "source_frame": "MaleCNS native unmirrored EM",
        "units": "um",
        "record_bytes": 28,
        "edges_per_neuron_max": 8,
        "chunks": chunks,
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(doc))
    (tmp_path / chunks[0]["file"]).write_bytes(raw)
    assert len(overview_manifest(tmp_path)["chunks"]) == 17
    assert overview_chunk(tmp_path, chunks[0]["file"]) == raw
    with pytest.raises(FileNotFoundError):
        overview_chunk(tmp_path, "../outside")
    (tmp_path / chunks[0]["file"]).write_bytes(b"x" * len(raw))
    with pytest.raises(ValueError, match="checksum"):
        overview_chunk(tmp_path, chunks[0]["file"])
    doc["chunks"].pop()
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="coverage"):
        overview_manifest(tmp_path)
