import copy
import hashlib
import zlib

import numpy as np
import pytest

from service.infrastructure.stimulation.geometry_cache import chunk, selected_chunk
from tests.test_packed_geometry_chunk import sources  # noqa: F401


@pytest.mark.parametrize('compression', ['none', 'zlib-1'])
def test_selected_decoder_matches_original_and_preserves_order(sources, tmp_path, compression):  # noqa: F811
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    descriptor = chunk.write_chunk(path, entries, audited_sources=audited, compression=compression)
    original = chunk.read_chunk(path, descriptor, audited_sources=audited)
    for wanted in ({10}, {20}, {10, 20}, set()):
        actual = selected_chunk.read_selected_chunk(path, descriptor,
                                                    audited_sources=audited, wanted=wanted)
        expected = [item for item in original if int(item['skeleton']['body_id']) in wanted]
        assert [item['skeleton'] for item in actual] == [item['skeleton'] for item in expected]
        for a, b in zip(actual, expected, strict=True):
            for array_a, array_b in zip(a['geometry'], b['geometry'], strict=True):
                np.testing.assert_array_equal(array_a, array_b)


@pytest.mark.parametrize('kind', ['gap', 'overlap', 'count', 'duplicate', 'missing_source'])
def test_selected_decoder_checks_metadata_for_unselected_entries(sources, tmp_path, kind):  # noqa: F811
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    desc = chunk.write_chunk(path, entries, audited_sources=audited, compression='zlib-1')
    desc = copy.deepcopy(desc)
    audited = dict(audited)
    if kind == 'gap':
        desc['neurons'][1]['offset'] += 1
    elif kind == 'overlap':
        desc['neurons'][1]['offset'] -= 1
    elif kind == 'count':
        desc['neurons'][1]['count'] += 1
    elif kind == 'duplicate':
        desc['neurons'][1]['body_id'] = '10'
        desc['neurons'][1]['source_sha256'] = audited[10]
    else:
        del audited[20]
    for reader in (lambda: chunk.read_chunk(path, desc, audited_sources=audited),
                   lambda: selected_chunk.read_selected_chunk(
                       path, desc, audited_sources=audited, wanted={10})):
        with pytest.raises(ValueError):
            reader()


@pytest.mark.parametrize('variant', ['trailing', 'truncated', 'oversize', 'invalid'])
def test_selected_decoder_checks_entire_compressed_stream(sources, tmp_path, variant):  # noqa: F811
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    desc = chunk.write_chunk(path, entries, audited_sources=audited, compression='zlib-1')
    data = path.read_bytes()
    if variant == 'trailing':
        data += b'junk'
    elif variant == 'truncated':
        data = data[:-1]
    elif variant == 'oversize':
        data = zlib.compress(b'0' * 241)
    else:
        data = b'invalid'
    path.write_bytes(data)
    desc['bytes'], desc['sha256'] = len(data), hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError, match='compressed geometry'):
        selected_chunk.read_selected_chunk(path, desc, audited_sources=audited, wanted={10})


def test_selected_decoder_rejects_changed_bytes_even_outside_selection(sources, tmp_path):  # noqa: F811
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    desc = chunk.write_chunk(path, entries, audited_sources=audited)
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(ValueError, match='checksum'):
        selected_chunk.read_selected_chunk(path, desc, audited_sources=audited, wanted={10})


@pytest.mark.parametrize('wanted', [[10], {True}, {'10'}, {0}, {-1}])
def test_selected_decoder_rejects_invalid_ids(sources, tmp_path, wanted):  # noqa: F811
    entries, audited = sources
    path = tmp_path / 'chunk.bin'
    desc = chunk.write_chunk(path, entries, audited_sources=audited)
    with pytest.raises(ValueError, match='selected geometry IDs'):
        selected_chunk.read_selected_chunk(path, desc, audited_sources=audited, wanted=wanted)


def test_optimized_reader_is_bound_to_reviewed_chunk_source(monkeypatch):
    from pathlib import Path

    digest = hashlib.sha256(Path(chunk.__file__).read_bytes()).hexdigest()
    monkeypatch.setattr(selected_chunk, 'REVIEWED_CHUNK_SHA256', digest)
    assert selected_chunk.supports_reader()
    monkeypatch.setattr(selected_chunk, 'REVIEWED_CHUNK_SHA256', '0' * 64)
    assert not selected_chunk.supports_reader()
