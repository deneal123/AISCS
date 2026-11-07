import hashlib
from uuid import uuid4

import httpx
import pytest

from service.services.simulations.inputs.replay_source import ReplaySource
from service.services.simulations.inputs.replay_transfer import ReplayTransferError, stage_replay_input


class Storage:
    def __init__(self, data):
        self.data = data

    async def download_file_stream(self, *, file_key, target, max_bytes):
        assert file_key == 'owned/object' and len(self.data) <= max_bytes
        target.write(self.data)
        return len(self.data)


def source(data):
    return ReplaySource({}, uuid4(), 'owned/object', hashlib.sha256(data).hexdigest(), len(data))


@pytest.mark.asyncio
async def test_transfer_verified_source_and_receipt():
    data = b'activity' * 150_000
    item, execution = source(data), uuid4()

    async def handler(request):
        assert request.url.path == f'/v1/replay-inputs/{execution}'
        assert request.headers['x-content-sha256'] == item.sha256
        assert int(request.headers['content-length']) == len(data)
        assert await request.aread() == data
        return httpx.Response(200, json={'sha256': item.sha256, 'bytes': len(data)})

    async with httpx.AsyncClient(
        base_url='http://generator', transport=httpx.MockTransport(handler)
    ) as client:
        await stage_replay_input(Storage(data), client, execution, item)


@pytest.mark.asyncio
async def test_corrupt_source_is_not_uploaded():
    data = b'correct'
    async def handler(_request):
        pytest.fail('corrupt data reached executor')

    async with httpx.AsyncClient(
        base_url='http://generator', transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ReplayTransferError, match='source_checksum_mismatch'):
            await stage_replay_input(Storage(b'corrupt'), client, uuid4(), source(data))
        with pytest.raises(ReplayTransferError, match='source_size_mismatch'):
            await stage_replay_input(Storage(b'short'), client, uuid4(), source(data))


@pytest.mark.asyncio
async def test_rejects_invalid_receipt():
    data = b'journal'
    async def handler(_request):
        return httpx.Response(200, json={'sha256': source(data).sha256, 'bytes': True})

    async with httpx.AsyncClient(
        base_url='http://generator', transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ReplayTransferError, match='invalid_executor_receipt'):
            await stage_replay_input(Storage(data), client, uuid4(), source(data))
