"""The private audit must finalize accepted usage before its caller times out."""

import ast
import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.presentation.routers.capabilities import document_audit as endpoint
from service.shared import deadline


def test_boot_digest_covers_the_private_audit_budget_owner():
    from service.domain.documents import runtime_digest

    base = Path(runtime_digest.__file__).parent
    assert Path(endpoint.__file__).resolve() in {
        (base / name).resolve() for name in runtime_digest._RUNTIME_FILES
    }


def test_private_budget_leaves_headroom_in_the_actual_backend_rpc_contract():
    path = (
        Path(__file__).parents[2]
        / "backend/service/infrastructure/agents_client/document_audit/client.py"
    )
    if not path.exists():
        pytest.skip("superproject owns the independent backend RPC contract")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    timeout = next(
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SidecarClient"
        for kw in node.keywords
        if kw.arg == "timeout" and isinstance(kw.value, ast.Constant)
    )
    assert 0 < endpoint._AUDIT_BUDGET_SEC <= timeout - 30


@pytest.mark.asyncio
async def test_timeout_preserves_accepted_receipt_and_cancels_work_once(monkeypatch):
    monkeypatch.setattr(endpoint, "internal_auth", lambda _: None)
    monkeypatch.setattr(endpoint, "_AUDIT_BUDGET_SEC", 0.01, raising=False)
    cancelled = []

    async def audit(_ref, _build, *, execution):
        assert execution.run_deadline is deadline.current()
        execution.usage.record_usage(
            {"prompt": 30, "completion": 3},
            provider="gigachat",
            model="GigaChat-2-Max",
            kind="document_visual_audit",
            receipt_id="accepted-vision-call",
        )
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(endpoint, "audit_document_build", audit)
    async with asyncio.timeout(0.5):
        result = await endpoint.audit_document(
            endpoint.DocumentAuditRequest(build_id="fixture-build", workspace_ref={}),
            authorization="fixture-auth",
        )
    assert result["status"] == "timeout" and not result["passed"] and result["retryable"]
    assert result["usage"]["total"] == 33
    assert len(result["usage"]["calls"]) == 1
    assert result["usage"]["calls"][0]["receipt_id"] == "accepted-vision-call"
    assert cancelled == [True]
    assert deadline.current() is None


@pytest.mark.asyncio
async def test_cancelled_raster_releases_known_claim_without_provider_retry(monkeypatch):
    from service.domain.documents import visual_audit as audit

    entered = asyncio.Event()

    async def raster(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(audit, "require_execution", lambda value: value)
    monkeypatch.setattr(
        audit,
        "call",
        AsyncMock(
            return_value={
                "audit": {
                    "page_count": 1,
                    "source_digest": "a" * 64,
                    "artifact_sha256": "b" * 64,
                }
            }
        ),
    )
    monkeypatch.setattr(audit, "list_qualified_models", AsyncMock(return_value=["vision-model"]))
    monkeypatch.setattr(audit, "download_binary", raster)
    report = AsyncMock(return_value={"state": "visual_pending"})
    provider = AsyncMock()
    monkeypatch.setattr(audit, "_report", report)
    monkeypatch.setattr(audit, "invoke_model_call", provider)
    task = asyncio.create_task(
        audit.audit_document_build(
            {},
            "fixture-build",
            execution=SimpleNamespace(provider_snapshot=None),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    report.assert_awaited_once()
    assert not report.await_args.kwargs["passed"] and report.await_args.kwargs["retryable"]
    provider.assert_not_awaited()


@pytest.mark.skipif(os.getenv("S37_LIVE_AUDIT_DEADLINE") != "1", reason="isolated dev ASGI probe")
def test_linux_private_http_timeout_preserves_usage_without_a_provider_call():
    from service.domain.documents import visual_audit

    probe = """
import asyncio,hashlib,json,logging,sys
from pathlib import Path
logging.disable(logging.CRITICAL)
import httpx
from fastapi import FastAPI
from service.presentation.routers.capabilities import document_audit as endpoint
from service.domain.documents import visual_audit
from service.settings import config
from service.shared import deadline
expected=json.load(sys.stdin)
assert all(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==digest
 for module,digest in zip((endpoint,visual_audit),expected,strict=True))
cancelled=[]
async def stalled(ref,build,*,execution):
 assert execution.run_deadline is deadline.current()
 execution.usage.record_usage({'prompt':30,'completion':3},provider='gigachat',
  model='GigaChat-2-Max',kind='document_visual_audit',receipt_id='fixture-call')
 try: await asyncio.Event().wait()
 finally: cancelled.append(True)
async def main():
 # All fault overrides belong only to this short-lived test process.
 endpoint._AUDIT_BUDGET_SEC=0.03; endpoint.audit_document_build=stalled
 app=FastAPI(); app.include_router(endpoint.router)
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
  base_url='http://fixture.test',trust_env=False) as client:
  response=await client.post('/document-audit',json={'build_id':'fixture-build',
   'workspace_ref':{}},headers={'Authorization':'Bearer '+config.agents.llm_gateway_api_key})
  assert response.status_code==200
  result=response.json()
  assert result['status']=='timeout' and not result['passed'] and result['retryable']
  assert result['usage']['total']==33 and len(result['usage']['calls'])==1
  assert cancelled==[True] and deadline.current() is None
 print(json.dumps({'status':'timeout','calls':1,'total':33,'cancelled':True}))
try: asyncio.run(main())
except BaseException: print(json.dumps({'status':'probe_failed'})); raise SystemExit(1)
"""
    expected = [
        hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        for module in (endpoint, visual_audit)
    ]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-agents-1", "python", "-c", probe],
        input=json.dumps(expected),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "private_timeout_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "timeout",
        "calls": 1,
        "total": 33,
        "cancelled": True,
    }
