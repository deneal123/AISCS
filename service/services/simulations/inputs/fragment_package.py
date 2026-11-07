"""Package already-authorized fragment artifacts for an isolated target replay."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass

from service.infrastructure.storage.bounded_download import settled_thread

MAX_PACKAGE_BYTES = 512 * 1024 * 1024
BASE = ('signals.npz', 'model.json', 'source-provenance.jsonl',
        'fragment-population-preview.json')
ALLOWED = (BASE, (*BASE, 'fragment-events.bin'),
           (*BASE, 'fragment-events.bin', 'fragment-response.npz'),
           (*BASE, 'fragment-events.bin', 'fragment-response.npz', 'fragment-response.bin'),
           (*BASE, 'fragment-events.bin', 'fragment-response.npz', 'fragment-response.bin',
            'fragment-delta.bin'))


@dataclass(frozen=True)
class OwnedFragmentFile:
    name: str
    storage_key: str
    size: int
    sha256: str


def _member(name):
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    return info


async def build_fragment_package(storage, manifest, files, output):
    """Build a deterministic ZIP from records already checked for ownership.

    Never call with client-supplied storage paths. Downloads and the output are
    bounded; callers own and close the output stream on every exit path.
    """
    if (not isinstance(manifest, dict) or manifest.get('kind') != 'experimental-fragment-population'
            or not isinstance(manifest.get('files'), list) or not isinstance(files, list)
            or any(not isinstance(item, OwnedFragmentFile) for item in files)
            or tuple(item.name for item in files) not in ALLOWED
            or len(files) != len(manifest['files'])):
        raise ValueError('invalid_fragment_manifest')
    for item, row in zip(files, manifest['files'], strict=True):
        if (not isinstance(row, dict) or set(row) != {'name', 'bytes', 'sha256'}
                or row != {'name': item.name, 'bytes': item.size, 'sha256': item.sha256}
                or not isinstance(item.storage_key, str) or not item.storage_key
                or type(item.size) is not int or not 0 < item.size <= MAX_PACKAGE_BYTES
                or not isinstance(item.sha256, str)
                or not re.fullmatch(r'[a-f0-9]{64}', item.sha256)):
            raise ValueError('invalid_fragment_artifact')
    try:
        payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                              separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid_fragment_manifest') from exc
    if len(payload) > 65536 or sum(item.size for item in files) + len(payload) > MAX_PACKAGE_BYTES:
        raise ValueError('fragment_package_too_large')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        archive.writestr(_member('manifest.json'), payload)
        for item in files:
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as source:
                size = await storage.download_file_stream(file_key=item.storage_key, target=source,
                                                          max_bytes=item.size)
                if size != item.size or source.tell() != item.size:
                    raise ValueError('fragment_artifact_size_mismatch')
                def copy_verified(current=item, current_source=source):
                    current_source.seek(0)
                    digest = hashlib.sha256()
                    with archive.open(_member(current.name), 'w', force_zip64=True) as destination:
                        while chunk := current_source.read(1024 * 1024):
                            digest.update(chunk)
                            destination.write(chunk)
                    if digest.hexdigest() != current.sha256:
                        raise ValueError('fragment_artifact_checksum_mismatch')
                await settled_thread(copy_verified)
    if output.tell() > MAX_PACKAGE_BYTES:
        raise ValueError('fragment_package_too_large')
    def package_digest():
        size = output.tell()
        output.seek(0)
        digest = hashlib.sha256()
        while chunk := output.read(1024 * 1024):
            digest.update(chunk)
        output.seek(0)
        return {'sha256': digest.hexdigest(), 'bytes': size,
                'manifest_sha256': hashlib.sha256(payload).hexdigest()}
    return await settled_thread(package_digest)


async def stage_fragment_package(storage, client, execution_id, source, *, expected_package_sha,
                                 expected_manifest_sha):
    """Rebuild and upload an owned source only if both immutable digests match."""
    from uuid import UUID

    if (not isinstance(execution_id, UUID)
            or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                   for value in (expected_package_sha, expected_manifest_sha))):
        raise ValueError('invalid_fragment_transfer')
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b') as stream:
        receipt = await build_fragment_package(storage, source.manifest, source.files, stream)
        if (receipt['sha256'] != expected_package_sha
                or receipt['manifest_sha256'] != expected_manifest_sha):
            raise ValueError('fragment_source_changed')

        async def chunks():
            while chunk := await settled_thread(lambda: stream.read(1024 * 1024)):
                yield chunk

        response = await client.put(f'/v1/replay-inputs/{execution_id}', content=chunks(),
            headers={'X-Content-SHA256': receipt['sha256'],
                     'Content-Length': str(receipt['bytes'])})
        response.raise_for_status()
        try:
            returned = response.json()
        except ValueError as exc:
            raise ValueError('invalid_executor_receipt') from exc
        if (not isinstance(returned, dict) or returned.get('sha256') != receipt['sha256']
                or type(returned.get('bytes')) is not int or returned['bytes'] != receipt['bytes']):
            raise ValueError('invalid_executor_receipt')
        return receipt
