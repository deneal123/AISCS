import gzip
import hashlib
import json
import struct

import pytest

from scripts.export_cns_overview import export_chunk, sample_swc_edges
from service.infrastructure.connectome.morphology_repository import BASE


def test_sampling_retains_original_edges_without_bridging():
    swc = "1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n3 0 250 0 0 1 2\n4 0 125 125 0 1 2\n"
    all_edges = sample_swc_edges(swc, 8)
    assert all_edges == [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (2, 0, 0)), ((1, 0, 0), (1, 1, 0))]
    assert sample_swc_edges(swc, 2) == [all_edges[0], all_edges[2]]
    assert sample_swc_edges("1 0 0 0 0 1 -1\n", 8) == []
    with pytest.raises(ValueError):
        sample_swc_edges(swc, 0)


def test_chunk_records_graph_identity_and_rejects_corrupt_source(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n2 0 125 0 0 1 1\n"
    (tmp_path / "raw" / "42.swc").write_bytes(raw)
    (tmp_path / "receipts" / "42.json").write_text(
        json.dumps(
            {"body_id": 42, "url": BASE + "42.swc", "sha256": hashlib.sha256(raw).hexdigest()}
        )
    )
    result, cells = export_chunk([42], 10, [tmp_path], 8)
    assert cells == 1
    assert struct.unpack("<Iffffff", gzip.decompress(result)) == (10, 0, 0, 0, 1, 0, 0)
    (tmp_path / "raw" / "42.swc").write_bytes(raw + b"corrupt")
    with pytest.raises(ValueError):
        export_chunk([42], 10, [tmp_path], 8)
