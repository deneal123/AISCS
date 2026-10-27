"""Opt-in native dev process privacy, with mocked stores and no destructive calls."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULES = (
    "service/infrastructure/memory/base.py",
    "service/infrastructure/memory/memos.py",
    "service/infrastructure/memory/diagnostics.py",
    "service/services/analytics/application/memory/service.py",
)
_PROBE = r"""
import asyncio,hashlib,json,logging,sys
from pathlib import Path
from unittest.mock import patch
import httpx
from service.infrastructure.memory import base,memos,diagnostics
from service.services.analytics.application.memory import (
 service as memory_service, cache as memory_cache,
)
wire=json.load(sys.stdin);stage='source_parity'
class Capture(logging.Handler):
 def __init__(self):super().__init__();self.records=[]
 def emit(self,record):self.records.append(record)
def capture(logger,handler):
 logger.handlers=[handler];logger.propagate=False;logger.disabled=False;logger.setLevel(logging.DEBUG)
async def main():
 global stage
 for module,digest in zip((base,memos,diagnostics,memory_service),wire['digests'],strict=True):
  assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 stage='integration'
 handler=Capture();integration=base.NoopMemoryIntegration();capture(integration.logger,handler)
 marker='private-memory-marker'
 started=integration._log_operation_start(marker,user_id=marker,fact_id=marker,facts=3)
 integration._log_operation_success(marker,started,path=marker,content=marker,facts=3)
 integration._log_operation_failure(marker,started,RuntimeError(marker))
 assert len(handler.records)==3
 assert handler.records[0].facts==3 and handler.records[1].facts==3
 assert all(r.operation=='other' for r in handler.records)
 stage='transport'
 def failed(request):raise httpx.ConnectError(marker)
 # Explicit mock transport and empty key: no request can reach the real MemOS.
 remote=memos.MemOSMemoryIntegration(base_url='http://memory.invalid',api_key='',
  transport=httpx.MockTransport(failed))
 capture(remote.logger,handler)
 assert await remote.wipe()=={'ok':False,'error':'transport'}
 assert await remote.forget_user(user_id='private-owner-marker')=={'ok':False,'error':'transport'}
 stage='service'
 private_error=type('PrivateMemoryMarker',(RuntimeError,),{})
 class FailedStore:
  async def delete_all_facts(self,**kwargs):raise private_error(marker)
  async def forget_user(self,**kwargs):raise private_error(marker)
 async def invalidate(_owner):return None
 capture(memory_service.logger,handler)
 with patch.object(memory_cache,'invalidate',invalidate):
  service=memory_service.MemoryService(integration=FailedStore(),facts_repo=FailedStore())
  result=await service.forget_everything('private-owner-marker')
 assert result=={'facts_deleted':0,'facts_error':'unavailable',
  'memos':{'ok':False,'error':'unavailable'}}
 stage='redaction'
 assert all(r.exc_info is None and r.component=='memory' for r in handler.records)
 assert all(value not in str([r.__dict__ for r in handler.records])
  for value in (marker,'private-owner-marker','PrivateMemoryMarker','memory.invalid'))
 assert all(getattr(r,'failure_code',None) in (None,'transport','unavailable')
  for r in handler.records)
 return {'status':'passed','cases':6,'model_calls':0,'database_calls':0,
  'real_memory_requests':0,'private_diagnostics_absent':True}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_private_probe_compiles():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_MEMORY_PRIVACY") != "1", reason="native dev diagnostic probe"
)
def test_current_dev_memory_boundaries_redact_private_failures():
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", _PROBE],
        input=json.dumps(
            {"digests": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in _MODULES]}
        ).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("memory_privacy_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {"source_parity", "integration", "transport", "service", "redaction"}:
            stage = "unknown"
        pytest.fail("memory_privacy_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 6,
        "model_calls": 0,
        "database_calls": 0,
        "real_memory_requests": 0,
        "private_diagnostics_absent": True,
    }
