"""Opt-in isolated Linux ASGI transport probe, not paid vision acceptance."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,logging,sys,uuid
logging.disable(logging.CRITICAL)
from pathlib import Path
from types import SimpleNamespace
import httpx
from fastapi import FastAPI
from service.settings import config
from service.presentation.routers.capabilities import document_audit as endpoint
from service.presentation.routers.capabilities import audit_usage_stream as stream
from service.presentation.routers.capabilities import managed_document_audit as managed
from service.presentation.routers.agent.usage_checkpoint import USAGE_KEY
expected=json.load(sys.stdin)
assert [hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
 for m in (endpoint,stream)]==expected
async def audit(ref,build,*,execution,usage_checkpoint=None):
 execution.usage.record_usage({'prompt':30,'completion':3},provider='gigachat',
  model='GigaChat-2-Max',kind='document_visual_audit',receipt_id='fixture-call')
 await asyncio.sleep(0)
 return SimpleNamespace(status='failed',passed=False,retryable=False,diagnostics=())
endpoint.audit_document_build=audit
app=FastAPI(); app.include_router(endpoint.router)
async def main():
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
   base_url='http://fixture.test',trust_env=False) as client:
  body={'build_id':'fixture-build','workspace_ref':{'user_id':str(uuid.uuid4()),
   'workspace_id':'fixture-workspace'},'checkpoint_attempt_id':str(uuid.uuid4()),'fresh_attempt':True}
  denied=await client.post('/document-audit/v2',json=body)
  assert denied.status_code in (401,403)
  response=await client.post('/document-audit/v2',json=body,
   headers={'Authorization':'Bearer '+config.agents.llm_gateway_api_key})
  assert response.status_code==200
  assert response.headers['content-type'].startswith('application/x-ndjson')
  frames=[json.loads(line) for line in response.text.splitlines()]
  assert len(frames)==2 and frames[0][USAGE_KEY]['attempt_id']==body['checkpoint_attempt_id']
  assert frames[0][USAGE_KEY]['receipts'][0]['receipt_id']=='fixture-call'
  assert frames[1][stream.RESULT_KEY]['usage']['total']==33
  assert not frames[1][stream.RESULT_KEY]['passed']
  recovery=await client.post('/document-audit/v2',json={**body,'recovery_only':True},
   headers={'Authorization':'Bearer '+config.agents.llm_gateway_api_key})
  snapshot=recovery.json(); assert snapshot['state']=='terminal'
  assert len(snapshot['checkpoint']['receipts'])==1 and 'producer_token' not in recovery.text
  registry=managed.registry_for(endpoint.DocumentAuditRequest(**body))
  assert await registry.redis.delete(registry.key)==1
 print(json.dumps({'status':'passed','frames':2,'calls':1,'total':33,'auth_checked':True}))
try: asyncio.run(main())
except BaseException: print(json.dumps({'status':'failed'})); raise SystemExit(1)
"""


def test_probe_is_valid_python():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_AUDIT_STREAM") != "1", reason="opt-in isolated dev ASGI process"
)
def test_private_checkpoint_wire_and_auth_in_linux_runtime():
    base = Path("service/presentation/routers/capabilities")
    expected = [
        hashlib.sha256((base / name).read_bytes()).hexdigest()
        for name in ("document_audit.py", "audit_usage_stream.py")
    ]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-c", _PROBE],
        input=json.dumps(expected).encode(),
        capture_output=True,
        timeout=30,
    )
    lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
    assert result.returncode == 0 and lines, "private_audit_stream_probe_failed"
    assert json.loads(lines[-1]) == {
        "status": "passed",
        "frames": 2,
        "calls": 1,
        "total": 33,
        "auth_checked": True,
    }
