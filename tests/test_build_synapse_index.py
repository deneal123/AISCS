import hashlib
import json

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pytest

from scripts import build_synapse_index as builder


def test_builder_verifies_graph_and_source_before_publication(tmp_path, monkeypatch):
    graph = tmp_path / 'graph'
    graph.mkdir()
    np.save(graph / 'ids.npy', np.array([1, 2], dtype=np.int64))
    ids_hash = hashlib.sha256((graph / 'ids.npy').read_bytes()).hexdigest()
    manifest = json.dumps({'arrays': {'ids.npy': ids_hash}}).encode()
    (graph / 'manifest.json').write_bytes(manifest)
    monkeypatch.setattr(builder, 'MANIFEST_SHA256', hashlib.sha256(manifest).hexdigest())
    source = tmp_path / 'source.arrow'
    table = pa.table({'body_pre': [1], 'body_post': [2]})
    with pa.OSFile(str(source), 'wb') as sink:
        with ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    digest = hashlib.md5(source.read_bytes(), usedforsecurity=False).hexdigest()
    monkeypatch.setattr(builder, 'SOURCE_MD5', digest)
    progress = []
    result = builder.prepare(
        source, graph, tmp_path / 'index', progress=lambda *args: progress.append(args)
    )
    assert result['neurons'] == 2 and result['batches'] == 1
    assert progress == [('source_verified', 0, 0), ('indexing', 1, 1)]
    np.save(graph / 'ids.npy', np.array([1, 3], dtype=np.int64))
    with pytest.raises(ValueError, match='ID checksum'):
        builder.prepare(source, graph, tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()
