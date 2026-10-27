"""Opt-in exact-source blob probe; no DB rows, runtime allocation or user data."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

MODULES = (
    "service.infrastructure.ide.checkpoint_storage",
    "service.infrastructure.storage.abstract_file_storage",
    "service.infrastructure.storage.bounded_download",
    "service.infrastructure.storage.local_file_storage",
    "service.infrastructure.storage.minio_file_storage",
    "service.infrastructure.storage.stream_upload_contract",
    "service.infrastructure.storage.identity",
    "service.services.chat.domain.ide.checkpoints.blob",
    "service.services.chat.domain.ide.runtime",
)

PROBE = r"""
import asyncio, hashlib, importlib, io, json, logging, tempfile, uuid
from dataclasses import replace
from pathlib import Path
from minio.error import S3Error
from service.composition.storage import build_file_storage
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.settings import Config
logging.disable(logging.CRITICAL)
stage = 'source_parity'

async def absent(storage, key):
 try:
  await asyncio.to_thread(storage._client.stat_object, storage._bucket, key)
 except S3Error as error:
  assert error.code == 'NoSuchKey'
 else:
  raise AssertionError('fixture_not_absent')

async def main():
 global stage
 for name, digest in EXPECTED_DIGESTS.items():
  module = importlib.import_module(name)
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == digest
 stage = 'setup'
 config = Config(); assert config.storage.backend == 'minio'
 remote = build_file_storage(config)
 scope = RepositoryScope(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
 count = 0
 with tempfile.TemporaryDirectory(prefix='ide-checkpoint-fixture-') as directory:
  local = LocalFileStorage(directory)
  for storage in (local, remote):
   for size in (0, 9, 1048593):
    body = (b'synthetic\0\xff' * (size // 11 + 1))[:size]
    blob = CheckpointBlob(scope, uuid.uuid4(), hashlib.sha256(body).hexdigest(), len(body))
    key = blob.key_for(scope)
    try:
     stage = 'binary_roundtrip_' + ('minio' if storage is remote else 'local') + '_' + str(size)
     await IdeCheckpointStorage(storage, max_bytes=len(body)).put(scope, blob, io.BytesIO(body))
     # New instance, not a cached stream. Remote uses a new SDK client too.
     fresh = build_file_storage(config) if storage is remote else LocalFileStorage(directory)
     service = IdeCheckpointStorage(fresh, max_bytes=len(body))
     async with service.open(scope, blob) as stream:
      assert stream.tell() == 0 and stream.read() == body
     assert stream.closed
     count += 1
     stage = 'scope_rejection'
     for changed in ('user_id', 'thread_id', 'repository_id'):
      foreign = replace(scope, **{changed: uuid.uuid4()})
      try:
       async with service.open(foreign, blob):
        raise AssertionError('cross_scope_opened')
      except IdeCheckpointError as error:
       assert error.code == 'ide_checkpoint_scope_forbidden'
      count += 1
     stage = 'overflow'
     target = io.BytesIO()
     try:
      await storage.download_file_stream(file_key=key, target=target, max_bytes=max(0,size-1))
     except ValueError as error:
      assert size > 0 and str(error) == 'storage_download_limit_exceeded'
     else:
      assert size == 0
     assert len(target.getvalue()) <= max(0,size-1)
     count += 1
     stage = 'same_size_corruption'
     if size:
      await storage.upload_file(file_key=key, file_data=b'x' * len(body))
      try:
       async with service.open(scope, blob):
        raise AssertionError('corrupt_opened')
      except IdeCheckpointError as error:
       assert error.code == 'ide_checkpoint_integrity_failed'
      count += 1
    finally:
     await storage.delete_file(file_key=key)
     if storage is remote: await absent(storage, key)
     else: assert not (Path(directory) / key).exists()
 return {'status':'passed', 'cases':count, 'source_parity':True,
         'fixtures_cleaned':True, 'user_file_rows':0, 'runtime_allocations':0}

try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_IDE_CHECKPOINT_STORAGE") != "1",
    reason="exact-source local/dev MinIO fixture opt-in",
)
def test_checkpoint_bytes_on_real_minio_and_posix_local():
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
    # Closed probe diagnostics, never print SDK exceptions/config/keys/contents.
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        pytest.fail("ide_checkpoint_probe_output_invalid")
    assert result.returncode == 0, f"ide_checkpoint_probe_failed:{outcome.get('stage')}"
    assert outcome == {
        "status": "passed",
        "cases": 34,
        "source_parity": True,
        "fixtures_cleaned": True,
        "user_file_rows": 0,
        "runtime_allocations": 0,
    }
