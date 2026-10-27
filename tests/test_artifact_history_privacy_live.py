"""Opt-in native diagnostic probe; all signer failures are test-boundary fixtures."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULE = "service/services/chat/persistence/chat_persistence_service.py"
_CONTAINERS = (
    "gpthub-dev-backend-1",
    "gpthub-dev-celery-worker-agents-1",
    "gpthub-dev-celery-worker-maintenance-1",
)
_STAGES = {"source_parity", "failure", "independent_success", "cancel", "owned_id", "redaction"}
_PROBE = r"""
import asyncio,hashlib,json,logging,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from service.services.chat.persistence import chat_persistence_service as module
wire=json.load(sys.stdin);stage='source_parity'
class Capture(logging.Handler):
 def __init__(self):super().__init__();self.records=[]
 def emit(self,record):self.records.append(record)
async def main():
 global stage
 assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==wire['source_digest']
 logger=module.logger;handler=Capture()
 logger.handlers=[handler];logger.propagate=False;logger.disabled=False
 logger.setLevel(logging.DEBUG)
 marker='PRIVATE_ARTIFACT_HISTORY_RUNTIME_SENTINEL'
 stage='failure'
 for failure in (RuntimeError,TimeoutError):
  signer=AsyncMock(side_effect=failure('https://private.invalid/'+marker+'?credential='+marker))
  service=module.ChatPersistenceService(None,SimpleNamespace(get_presigned_url_by_key=signer))
  item={'file_key':marker,'file_url':'https://stale.invalid/owned','filename':'file.pdf'}
  meta={'generated_files':[item],'usage':{'total':17}}
  result=await service._refresh_artifact_links(meta)
  assert result['generated_files']==[item] and result['usage']==meta['usage']
  assert result['file_url']==item['file_url'] and signer.await_count==1
 stage='independent_success'
 signer=AsyncMock(side_effect=[RuntimeError(marker),'https://fresh.invalid/owned'])
 service=module.ChatPersistenceService(None,SimpleNamespace(get_presigned_url_by_key=signer))
 original={'generated_files':[{'file_key':'one','file_url':'https://old.invalid/one'},
  {'file_key':'two','file_url':'https://old.invalid/two'}]}
 result=await service._refresh_artifact_links(original)
 assert signer.await_count==2
 assert result['generated_files'][0]['file_url']=='https://old.invalid/one'
 assert result['generated_files'][1]['file_url']=='https://fresh.invalid/owned'
 assert original['generated_files'][1]['file_url']=='https://old.invalid/two'
 stage='cancel'
 signer=AsyncMock(side_effect=asyncio.CancelledError())
 service=module.ChatPersistenceService(None,SimpleNamespace(get_presigned_url_by_key=signer))
 cancelled={'generated_files':[{'file_key':'one'},{'file_key':'two'}]}
 try:await service._refresh_artifact_links(cancelled)
 except asyncio.CancelledError:pass
 else:raise AssertionError('cancel_not_propagated')
 assert signer.await_count==1
 stage='owned_id'
 signer=AsyncMock(side_effect=AssertionError('owned_id_must_not_presign'))
 service=module.ChatPersistenceService(None,SimpleNamespace(get_presigned_url_by_key=signer))
 meta={'generated_files':[{'file_id':'owned-id','filename':'owned.pdf'}]}
 result=await service._refresh_artifact_links(meta)
 assert result['generated_files']==[{**meta['generated_files'][0],'file_url':None}]
 assert signer.await_count==0
 stage='redaction'
 assert len(handler.records)==3
 assert all(r.exc_info is None and r.stack_info is None and
  r.component=='artifact_history' and r.failure_code=='unavailable' and
  r.getMessage()=='artifact link refresh failed: unavailable' for r in handler.records)
 assert not any(value in str([r.__dict__ for r in handler.records])
  for value in (marker,'private.invalid','credential='))
 return {'status':'passed','cases':5,'model_calls':0,'database_calls':0,
  'real_storage_requests':0,'private_diagnostics_absent':True}
try:report=asyncio.run(main())
except BaseException:report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_history_probe_is_syntax_valid_and_only_mocks_signer_io():
    ast.parse(_PROBE)
    assert "AsyncMock" in _PROBE
    assert not any(word in _PROBE for word in ("httpx", "urllib", "Config()", "create_session"))


@pytest.mark.parametrize("container", _CONTAINERS)
@pytest.mark.skipif(
    os.getenv("S37_LIVE_ARTIFACT_HISTORY_PRIVACY") != "1", reason="native dev diagnostic probe"
)
def test_current_dev_history_boundaries_redact_private_signer_failure(container):
    digest = hashlib.sha256(Path(_MODULE).read_bytes()).hexdigest()
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", _PROBE],
        input=json.dumps({"source_digest": digest}).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("artifact_history_privacy_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in _STAGES:
            stage = "unknown"
        pytest.fail("artifact_history_privacy_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 5,
        "model_calls": 0,
        "database_calls": 0,
        "real_storage_requests": 0,
        "private_diagnostics_absent": True,
    }
