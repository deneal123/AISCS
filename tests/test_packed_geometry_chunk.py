import copy
import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.geometry_cache import chunk as packed_geometry_chunk
from service.infrastructure.stimulation.network_field import _prepare_gpu_skeleton


@pytest.fixture
def sources(tmp_path):
    (tmp_path / 'raw').mkdir()
    (tmp_path / 'receipts').mkdir()
    bodies = {
        10: b'1 0 100.5 2 3 4 -1\n2 0 110 4 3 5 1\n3 0 115 6 3 3 2\n',
        20: b'2 0 150 3 3 2 1\n1 0 140 2 3 3 -1\n4 0 160 4 3 1 1\n',
    }
    audited = {}
    for body, raw in bodies.items():
        sha = hashlib.sha256(raw).hexdigest()
        (tmp_path / 'raw' / f'{body}.swc').write_bytes(raw)
        (tmp_path / 'receipts' / f'{body}.json').write_text(json.dumps(
            {'body_id': body, 'sha256': sha, 'url': BASE + f'{body}.swc'}))
        audited[body] = sha
    entries = [_prepare_gpu_skeleton((body, [tmp_path])) for body in bodies]
    return entries, audited


def test_checked_geometry_round_trip_is_lossless(sources, tmp_path):
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    description = packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    assert description['vertices'] == 6 and description['bytes'] == 240
    assert hashlib.sha256(path.read_bytes()).hexdigest() == description['sha256']
    restored = packed_geometry_chunk.read_chunk(path, description, audited_sources=audited)
    assert [entry['skeleton'] for entry in restored] == [entry['skeleton'] for entry in entries]
    for original, loaded in zip(entries, restored, strict=True):
        for expected, actual in zip(original['geometry'], loaded['geometry'], strict=True):
            np.testing.assert_array_equal(expected, actual)
    assert restored[0]['points'][0, 0] == 100.5 * .008


def test_rejects_changed_bytes_and_untrusted_or_wrong_source(sources, tmp_path):
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    description = packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    with pytest.raises(ValueError, match='source identity'):
        packed_geometry_chunk.read_chunk(path, description,
                                         audited_sources={**audited, 10: '0' * 64})
    data = bytearray(path.read_bytes())
    data[0] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError, match='checksum'):
        packed_geometry_chunk.read_chunk(path, description, audited_sources=audited)
    with pytest.raises(FileExistsError):
        packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    assert path.read_bytes() == data


@pytest.mark.parametrize('change', ['gap', 'overlap', 'count', 'duplicate', 'missing_source'])
def test_rejects_invalid_chunk_manifest_before_read(sources, tmp_path, change):
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    description = packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    tampered = copy.deepcopy(description)
    if change == 'gap':
        tampered['neurons'][1]['offset'] += 1
    elif change == 'overlap':
        tampered['neurons'][1]['offset'] -= 1
    elif change == 'count':
        tampered['neurons'][1]['count'] += 1
    elif change == 'duplicate':
        tampered['neurons'][1]['body_id'] = '10'
        tampered['neurons'][1]['source_sha256'] = audited[10]
    else:
        del audited[20]
    with pytest.raises(ValueError):
        packed_geometry_chunk.read_chunk(path, tampered, audited_sources=audited)


def test_rejects_untrusted_sources_and_lossy_or_oversize_inputs(sources, tmp_path, monkeypatch):
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    with pytest.raises(ValueError, match='source identity'):
        packed_geometry_chunk.write_chunk(path, entries, audited_sources={10: '0' * 64})
    bad = copy.deepcopy(entries)
    ids, points, parents, radii = bad[0]['geometry']
    bad[0]['geometry'] = ids, points.astype(np.float32), parents, radii
    with pytest.raises(ValueError, match='float64'):
        packed_geometry_chunk.write_chunk(path, bad, audited_sources=audited)
    monkeypatch.setattr(packed_geometry_chunk, '_MAX_VERTICES', 5)
    with pytest.raises(ValueError, match='vertex limit'):
        packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    assert not path.exists()


def test_failed_flush_does_not_leave_a_published_chunk(sources, tmp_path, monkeypatch):
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    real_open = type(path).open

    class FailedClose:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()
            raise OSError('flush failed')

        def write(self, data):
            return self.stream.write(data)

    monkeypatch.setattr(type(path), 'open',
                        lambda p, *a, **kw: FailedClose(real_open(p, *a, **kw)))
    with pytest.raises(OSError, match='flush failed'):
        packed_geometry_chunk.write_chunk(path, entries, audited_sources=audited)
    assert not path.exists()
