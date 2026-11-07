import hashlib

import numpy as np
import pytest

from service.application.field import field_state_artifacts
from service.infrastructure.connectome.forced_network import contrast_forced_network
from tests.test_forced_network import graph


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_export_and_load_separate_bound_artifacts(tmp_path, monkeypatch):
    model = graph()
    model.provenance['manifest_sha256'] = 'a' * 64
    result = contrast_forced_network(model, seed=1, duration_ms=6, forced_cell_ids=[10],
                                     events={10: [1]}, sample_cell_ids=[20, 30])
    result['provenance'] = {'field_manifest_sha256': 'b' * 64,
                            'graph_manifest_sha256': 'a' * 64, 'graph_sha256': 'c' * 64}
    monkeypatch.setattr(field_state_artifacts, 'contrast_verified_field_run',
                        lambda *a, **kw: result)
    source, output = tmp_path / 'source', tmp_path / 'output'
    source.mkdir()
    manifest = field_state_artifacts.export_field_state_contrast(
        source, output, model, sample_cell_ids=[20, 30], expected_manifest_sha256='b' * 64)
    assert len(manifest['files']) == 2
    restored = field_state_artifacts.load_field_state_contrast(
        output, model, expected_manifest_sha256=digest(output / 'manifest.json'),
        expected_field_manifest_sha256='b' * 64, expected_graph_sha256='c' * 64)
    np.testing.assert_array_equal(restored['voltage_difference_mv'],
                                  result['voltage_difference_mv'])
    with pytest.raises(FileExistsError):
        field_state_artifacts.export_field_state_contrast(
            source, output, model, sample_cell_ids=[20], expected_manifest_sha256='b' * 64)
    with pytest.raises(ValueError, match='separate'):
        field_state_artifacts.export_field_state_contrast(
            source, source / 'nested', model, sample_cell_ids=[20],
            expected_manifest_sha256='b' * 64)
    with (output / 'state-contrast.bin').open('ab') as stream:
        stream.write(b'x')
    with pytest.raises(ValueError, match='size mismatch'):
        field_state_artifacts.load_field_state_contrast(
            output, model, expected_manifest_sha256=digest(output / 'manifest.json'),
            expected_field_manifest_sha256='b' * 64, expected_graph_sha256='c' * 64)


def test_loader_rejects_untrusted_result_manifest(tmp_path):
    model = graph()
    (tmp_path / 'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='trusted digest'):
        field_state_artifacts.load_field_state_contrast(
            tmp_path, model, expected_manifest_sha256='0' * 64,
            expected_field_manifest_sha256='b' * 64, expected_graph_sha256='c' * 64)
