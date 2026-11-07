import asyncio
import hashlib
from uuid import uuid4

import pytest

from service.infrastructure.execution.replay_input import ReplayInputStore


async def chunks(*values):
    for value in values:
        yield value


def test_streamed_upload_is_checked_idempotent_and_scoped(tmp_path):
    store, execution = ReplayInputStore(tmp_path), uuid4()
    digest = hashlib.sha256(b'abcdef').hexdigest()
    result = asyncio.run(store.put(execution, digest, chunks(b'abc', b'def')))
    assert result == {'sha256': digest, 'bytes': 6}
    assert store.path(execution).read_bytes() == b'abcdef'
    assert asyncio.run(store.put(execution, digest, chunks(b'abcdef'))) == result
    other = hashlib.sha256(b'other').hexdigest()
    with pytest.raises(ValueError, match='different replay input'):
        asyncio.run(store.put(execution, other, chunks(b'other')))
    assert store.path(execution).read_bytes() == b'abcdef'
    assert list(store.path(execution).parent.glob('*.pending')) == []
    with pytest.raises(ValueError, match='checksum mismatch'):
        store.discard(execution, other)
    assert store.discard(execution, digest)
    assert not store.discard(execution, digest)
    assert not store.path(execution).exists()


def test_checksum_failure_and_invalid_execution_leave_no_input(tmp_path):
    store, execution = ReplayInputStore(tmp_path), uuid4()
    with pytest.raises(ValueError, match='checksum mismatch'):
        asyncio.run(store.put(execution, 'a' * 64, chunks(b'wrong')))
    assert not store.path(execution).exists()
    with pytest.raises(ValueError, match='execution ID'):
        asyncio.run(store.put('../other', 'a' * 64, chunks(b'data')))


def test_simultaneous_identical_uploads_do_not_overwrite(tmp_path):
    store, execution = ReplayInputStore(tmp_path), uuid4()
    digest = hashlib.sha256(b'data').hexdigest()
    async def upload():
        return await asyncio.gather(store.put(execution, digest, chunks(b'da', b'ta')),
                                    store.put(execution, digest, chunks(b'data')))
    result = asyncio.run(upload())
    assert result[0] == result[1]
    assert store.path(execution).read_bytes() == b'data'
