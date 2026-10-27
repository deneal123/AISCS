"""Installed prefix admission; synthetic storage only, no owned files or mutations."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILES = (
    "service/services/files/application/file_saver_service.py",
    "service/services/files/domain/file_read_limits.py",
)
_PROBE = """
import asyncio,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from service.services.files.application import file_saver_service as module
from service.services.files.domain import file_read_limits as limits
async def main():
 expected=json.load(sys.stdin)
 for source,name in zip((module,limits),expected['files']):
  assert hashlib.sha256(Path(source.__file__).read_bytes()).hexdigest()==expected['hashes'][name]
 cases=('private-response',{'private':'private-response'},False,
        bytearray(b'private'),memoryview(b'private'),None,b'',b'ab',b'0123456789')
 for ranged in (True,False):
  for payload in cases:
   whole=AsyncMock(return_value=payload)
   head=AsyncMock(return_value=payload) if ranged else None
   saver=object.__new__(module.FileSaverService)
   saver.storage=SimpleNamespace(get_file=whole,get_file_head=head)
   result=await saver.get_file_head_by_key(file_key='synthetic-prefix',max_bytes=4)
   assert result==(payload[:4] if isinstance(payload,bytes) else None)
   if ranged:
    head.assert_awaited_once_with('synthetic-prefix',4);whole.assert_not_awaited()
   else: whole.assert_awaited_once_with('synthetic-prefix')
 print(json.dumps({'status':'passed','cases':len(cases)*2,'source_matches':True,'real_reads':0}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','failure_code':'prefix_probe'}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_FILE_HEAD_ADMISSION") != "1", reason="opt-in installed prefix probe"
)
@pytest.mark.parametrize(
    "container",
    [
        "gpthub-dev-backend-1",
        "gpthub-dev-celery-worker-agents-1",
        "gpthub-dev-celery-worker-maintenance-1",
    ],
)
def test_installed_file_head_admission(container):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", _PROBE],
        input=json.dumps(
            {
                "files": _FILES,
                "hashes": {
                    name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in _FILES
                },
            }
        ),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "installed_prefix_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "cases": 18,
        "source_matches": True,
        "real_reads": 0,
    }
