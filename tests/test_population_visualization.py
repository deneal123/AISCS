import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.feedback.event_archive import EventArchive
from service.application.feedback.population_visualization import export_population_markers
from service.infrastructure.stimulation.population.source_events import HEADER


def test_exports_deduplicated_crossings_for_complete_population(tmp_path):
    graph = SimpleNamespace(ids=np.array([10, 20]), provenance={'manifest_sha256': 'a' * 64})
    archive = tmp_path / 'activity.jsonl'
    with EventArchive(archive) as writer:
        writer.write_batch({20: {'edge_events': [], 'candidates': [
            {'stimulated_ticks_ms': [1, 3]}, {'stimulated_ticks_ms': [3]}]}})
        writer.write_batch({10: {'edge_events': [], 'candidates': [
            {'stimulated_ticks_ms': [1]}]}})
        writer.commit()
        archive_hash = writer.sha256
    output = tmp_path / 'markers.bin'
    receipt = export_population_markers(output, archive, archive_hash, graph,
        duration_ms=5, configuration_sha256='b' * 64)
    raw = output.read_bytes()
    assert receipt['sha256'] == hashlib.sha256(raw).hexdigest()
    assert HEADER.unpack_from(raw)[:4] == (b'SRC1', 2, 5, 3)
    np.testing.assert_array_equal(np.frombuffer(raw, dtype='<u4', offset=HEADER.size),
                                  [0, 1, 1, 1, 1, 3])


def test_incomplete_or_changed_archive_leaves_no_output(tmp_path):
    graph = SimpleNamespace(ids=np.array([10, 20]), provenance={'manifest_sha256': 'a' * 64})
    archive = tmp_path / 'activity.jsonl'
    with EventArchive(archive) as writer:
        writer.write_batch({10: {'edge_events': [], 'candidates': []}})
        writer.commit()
        archive_hash = writer.sha256
    output = tmp_path / 'markers.bin'
    with pytest.raises(ValueError, match='Incomplete marker'):
        export_population_markers(output, archive, archive_hash, graph, duration_ms=5,
                                  configuration_sha256='b' * 64)
    with pytest.raises(ValueError, match='digest'):
        export_population_markers(output, archive, '0' * 64, graph, duration_ms=5,
                                  configuration_sha256='b' * 64)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == [archive]
