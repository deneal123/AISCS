"""Opt-in controlled failures in the loaded dev runtime; no real policy writes."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = r"""
import asyncio,hashlib,json,logging,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
from service.infrastructure import provider_policy_store as policy
marker='PRIVATE_POLICY_FAILURE_SENTINEL'
records=[]
class Capture(logging.Handler):
 def emit(self,record): records.append(record)
async def main(expected):
 assert hashlib.sha256(Path(policy.__file__).read_bytes()).hexdigest()==expected
 log=policy.logger
 with patch.object(log,'handlers',[Capture()]),patch.object(log,'propagate',False), \
      patch.object(log,'disabled',False),patch.object(log,'level',logging.DEBUG):
  for stage in ('prime','persist','seed','block','clear','read','names'):
   repo=SimpleNamespace(get_all=AsyncMock(side_effect=OSError(marker)),
    upsert=AsyncMock(side_effect=OSError(marker)))
   redis=SimpleNamespace(set=Mock(side_effect=OSError(marker)),
    delete=Mock(side_effect=OSError(marker)),mget=Mock(side_effect=OSError(marker)))
   with patch.object(policy,'_BLOCKED',{'gigachat':'unavailable'}), \
        patch.object(policy,'_repo',repo),patch.object(policy,'_get_redis',lambda:redis):
    if stage=='prime': await policy.prime()
    elif stage=='persist': await policy._persist_db()
    elif stage=='seed':
     repo.get_all=AsyncMock(return_value={'provider_blocked':{'gigachat':{'reason':marker}}})
     await policy.prime()
     assert policy._BLOCKED=={'gigachat':marker}
    elif stage=='block': await policy.set_blocked('gigachat','unavailable')
    elif stage=='clear':
     await policy.clear_blocked('gigachat'); assert not policy._BLOCKED
    elif stage=='read': assert await policy.blocked_providers()=={'gigachat'}
    else:
     await policy.set_blocked(marker,marker); await policy.clear_blocked(marker)
 assert records
 for record in records:
  assert marker not in repr(record.__dict__)
  assert record.exc_info is None and record.stack_info is None
  assert record.component=='provider_policy'
  assert record.failure_code in policy._DIAGNOSTIC_CODES
 return {'source_fresh':True,'controlled_stages':7,'raw_diagnostics':False}
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main(json.load(sys.stdin)['digest']))}))
except Exception:
 print(json.dumps({'status':'failed','stage':'provider_policy_privacy'})); raise SystemExit(1)
"""


def test_provider_policy_runtime_probe_is_syntax_valid():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_POLICY_PRIVACY") != "1", reason="explicit dev runtime acceptance"
)
def test_loaded_dev_policy_handles_controlled_failures_without_private_logs():
    source = Path(__file__).parents[1] / "service/infrastructure/provider_policy_store.py"
    payload = json.dumps({"digest": hashlib.sha256(source.read_bytes()).hexdigest()})
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=payload.encode(),
        capture_output=True,
        timeout=45,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "provider_policy_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "provider_policy_privacy_failed"
    assert report == {
        "status": "passed",
        "checks": {"source_fresh": True, "controlled_stages": 7, "raw_diagnostics": False},
    }
