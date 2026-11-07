import hashlib
import io
import zipfile
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.services.simulations.inputs.fragment_package import (
    BASE,
    OwnedFragmentFile,
    build_fragment_package,
    stage_fragment_package,
)


class Storage:
    async def download_file_stream(self, *, file_key, target, max_bytes):
        data = file_key.encode('ascii')
        assert len(data) <= max_bytes
        target.write(data)
        return len(data)


def fixture():
    files = [OwnedFragmentFile(name=name, storage_key=name, size=len(name),
                               sha256=hashlib.sha256(name.encode('ascii')).hexdigest())
             for name in BASE]
    manifest = {'kind': 'experimental-fragment-population', 'files': [
        {'name': f.name, 'bytes': f.size, 'sha256': f.sha256} for f in files]}
    return manifest, files


@pytest.mark.asyncio
async def test_package_is_deterministic_and_contains_only_checked_files():
    manifest, files = fixture()
    first, second = io.BytesIO(), io.BytesIO()
    receipt = await build_fragment_package(Storage(), manifest, files, first)
    assert receipt == await build_fragment_package(Storage(), manifest, files, second)
    assert first.getvalue() == second.getvalue()
    with zipfile.ZipFile(first) as package:
        assert package.namelist() == ['manifest.json', *BASE]
        assert package.read(BASE[0]) == BASE[0].encode('ascii')


@pytest.mark.asyncio
async def test_package_rejects_mismatched_and_unexpected_artifacts():
    manifest, files = fixture()
    with pytest.raises(ValueError, match='invalid_fragment_manifest'):
        await build_fragment_package(Storage(), manifest, files[::-1], io.BytesIO())
    manifest['files'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='invalid_fragment_artifact'):
        await build_fragment_package(Storage(), manifest, files, io.BytesIO())


@pytest.mark.asyncio
async def test_stage_checks_digests_before_upload_and_verifies_receipt():
    manifest, files = fixture()
    source = SimpleNamespace(manifest=manifest, files=files)
    receipt = await build_fragment_package(Storage(), manifest, files, io.BytesIO())
    class Client:
        def __init__(self):
            self.calls = 0

        async def put(self, _url, *, content, headers):
            self.calls += 1
            data = b''.join([chunk async for chunk in content])
            assert hashlib.sha256(data).hexdigest() == headers['X-Content-SHA256']
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    client = Client()
    await stage_fragment_package(Storage(), client, uuid4(), source,
        expected_package_sha=receipt['sha256'], expected_manifest_sha=receipt['manifest_sha256'])
    assert client.calls == 1
    with pytest.raises(ValueError, match='source_changed'):
        await stage_fragment_package(Storage(), client, uuid4(), source,
            expected_package_sha='0' * 64, expected_manifest_sha=receipt['manifest_sha256'])
    assert client.calls == 1
