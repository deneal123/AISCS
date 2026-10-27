"""Opt-in installed child-process expiry boundary; no Redis/DB/provider mutations."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,sys,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from service.infrastructure import workspace_client
from service.services.chat.infrastructure.chat_worker.materialization import workspace as module
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
async def main():
 expected=json.load(sys.stdin)
 assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==expected['digest']
 owner=str(uuid4())
 request=SimpleNamespace(user_id=owner,thread_id='expiry-probe',job_id=str(uuid4()))
 inventory=[{'path':'notes.md','size':5,'sha256':hashlib.sha256(b'notes').hexdigest(),'required':True}]
 facts={'workspace_id':'expiry-fixture','workspace_files':inventory}
 for expiry in (float('nan'),float('inf'),'NaN','Infinity','private-expiry-marker',{},10**1000):
  binding={'workspace_id':'expiry-fixture','user_id':owner,'expires_at':expiry}
  collector=AsyncMock(return_value=[])
  files=SimpleNamespace(save=AsyncMock())
  raw=json.dumps(binding).encode()
  with patch.object(workspace_client,'_redis_call',AsyncMock(return_value=raw)), \
       patch.object(workspace_client,'collect_artifacts',collector):
   try: await module.recover_workspace_files(request=request,facts=facts,metadata={},
                                             file_service=files,redis_client=object())
   except JobStateUnavailable as error: assert 'private-expiry-marker' not in str(error)
   else: raise AssertionError
  collector.assert_not_awaited();files.save.assert_not_awaited()
 assert module._live_expiry(time.time()+300)
 assert module._live_expiry(int(time.time())+300)
 print(json.dumps({'status':'passed','cases':7,'source_matches':True,'real_mutations':0}))
try: asyncio.run(main())
except BaseException:
 print(json.dumps({'status':'failed','failure_code':'expiry_probe'}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORKSPACE_MATERIALIZATION") != "1", reason="opt-in installed expiry probe"
)
@pytest.mark.parametrize(
    "container",
    [
        "gpthub-dev-backend-1",
        "gpthub-dev-celery-worker-agents-1",
        "gpthub-dev-celery-worker-maintenance-1",
    ],
)
def test_installed_workspace_materialization_expiry(container):
    source = Path(__file__).resolve().parents[1] / (
        "service/services/chat/infrastructure/chat_worker/materialization/workspace.py"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", _PROBE],
        input=json.dumps({"digest": hashlib.sha256(source.read_bytes()).hexdigest()}),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "installed_expiry_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "cases": 7,
        "source_matches": True,
        "real_mutations": 0,
    }
