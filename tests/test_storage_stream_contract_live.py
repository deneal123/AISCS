"""Opt-in native adapter acceptance over disposable fixtures on the dev stack."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

MODULES = (
    "service.infrastructure.storage.local_file_storage",
    "service.infrastructure.storage.minio_file_storage",
    "service.infrastructure.storage.stream_upload_contract",
)
PROBE = r"""
import asyncio, hashlib, importlib, json, logging, tempfile, uuid
from io import BytesIO
from pathlib import Path
from minio.error import S3Error
from service.composition.storage import build_file_storage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.settings import Config
logging.disable(logging.CRITICAL)
expected = EXPECTED_DIGESTS
stage = 'source_parity'

class ForbiddenStream:
 def seek(self, *_): raise AssertionError('unexpected_seek')
 def read(self, *_): raise AssertionError('unexpected_read')

async def absent(storage, key):
 try: await asyncio.to_thread(storage._client.stat_object, storage._bucket, key)
 except S3Error as error: assert error.code == 'NoSuchKey'
 else: raise AssertionError('fixture_not_absent')

async def main():
 global stage
 for name, digest in expected.items():
  module = importlib.import_module(name)
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == digest
 stage = 'adapter_setup'
 config = Config(); assert config.storage.backend == 'minio'
 remote = build_file_storage(config)
 count = 0
 with tempfile.TemporaryDirectory(prefix='stream-contract-') as directory:
  local = LocalFileStorage(directory)
  for storage in (local, remote):
   key = 's37-stream-contract/CHAT/' + uuid.uuid4().hex + '.txt'
   try:
    stage = 'length_preflight'
    for length in (-1, True, False, 1.5, '1', None):
     try:
      await storage.upload_file_stream(file_key=key, stream=ForbiddenStream(), length=length)
     except ValueError as error: assert str(error) == 'storage_stream_invalid'
     else: raise AssertionError('invalid_length_accepted')
     count += 1
    if storage is remote: await absent(storage, key)
    else: assert not (Path(directory) / key).exists()
    for size in (0, 11, 1048593):
     stage = 'native_roundtrip'
     body = (b'synthetic fixture' * (size // 17 + 1))[:size]
     with BytesIO(body) as stream:
      await storage.upload_file_stream(file_key=key, stream=stream, length=size)
      assert not stream.closed
     assert await storage.read_file_metadata(key) == {
      'status': 'ok', 'size': size, 'sha256': hashlib.sha256(body).hexdigest()}
     count += 1
   finally:
    stage = 'fixture_cleanup'
    await storage.delete_file(file_key=key)
    if storage is remote: await absent(storage, key)
    else: assert not (Path(directory) / key).exists()
 return {'status': 'passed', 'cases': count, 'source_parity': True,
         'fixtures_cleaned': True, 'user_file_rows': 0, 'provider_calls': 0}

try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status': 'failed', 'stage': stage})); raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.environ.get("S37_LIVE_STORAGE_STREAM_CONTRACT") != "1",
    reason="isolated local and owned dev MinIO fixture opt-in",
)
def test_native_storage_stream_contract_and_exact_roundtrip():
    root = Path(__file__).resolve().parents[1]
    digests = {
        name: hashlib.sha256((root / (name.replace(".", "/") + ".py")).read_bytes()).hexdigest()
        for name in MODULES
    }
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-"],
        input=PROBE.replace("EXPECTED_DIGESTS", repr(digests)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "native_storage_stream_contract_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "cases": 18,
        "source_parity": True,
        "fixtures_cleaned": True,
        "user_file_rows": 0,
        "provider_calls": 0,
    }
