"""Opt-in metered component acceptance, not Chat/browser certification.

Private fixture processes restrict provider policy to GigaChat without changing
deployment configuration. Compilation, the live agents audit endpoint, durable
attempt settlement, MinIO streaming and authenticated Library download are real.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import httpx
import pytest

from tests.test_literal_pdf_delivery_live import _inspect_pdf

_TOKEN = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.services.profile.application.auth_service import AuthService
from service.models.key_value import UserTypes
async def main():
 cfg=Config(); assert cfg.pg.host=='postgres'; db=PgConnector(cfg.pg)
 try:
  async with db.get_session_context() as session:
   owner=await session.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s38-video-acceptance@example.com'}); assert owner is not None
  auth=AuthService(cfg.auth.model_copy(update={'jwt_exp_hours':1}),None,None,cfg.email)
  print(json.dumps({'token':auth._create_jwt(owner,None,UserTypes.REGISTERED)}))
 finally: await db.close()
try: asyncio.run(main())
except BaseException: print(json.dumps({'failure':'fixture_auth_unavailable'})); raise SystemExit(1)
"""

_SETUP = """
import asyncio,json,logging,sys
logging.disable(logging.CRITICAL)
from service.settings import config
from service.composition.container import build_container
from service.infrastructure.workspace_client import ensure_workspace_explicit
from service.services.chat.application.workspace_collaboration import mint_capability
async def main():
 p=json.load(sys.stdin); c=build_container(config)
 try:
  owner=await c.repositories.profile_repository.fetch_user_by_email(
   's38-video-acceptance@example.com')
  assert owner is not None
  await c.services.chat_application_service.ensure_thread_owner(p['thread_id'],str(owner.id))
  ref=await ensure_workspace_explicit(c.infra.redis_client,p['thread_id'],str(owner.id))
  assert ref
  ref={**ref,'coordination_capability':mint_capability(str(ref['workspace_id']),
   role='agent',actor_seed=p['thread_id']+':'+str(owner.id),
   expires_at=float(ref.get('expires_at') or 0),run_id=p['thread_id'])}
  print(json.dumps({'workspace_ref':ref,'literal':p['literal']}))
 finally:
  if c.infra.redis_manager: await c.infra.redis_manager.close()
  await c.infra.pg_connector.close()
try: asyncio.run(main())
except BaseException: print(json.dumps({'failure':'setup_failed'})); raise SystemExit(1)
"""

_BUILD = """
import asyncio,json,logging,sys
logging.disable(logging.CRITICAL)
from service.domain.documents import literal_shortcut
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.client.registry import initialize_run_provider_admission
from service.presentation.cli.document_authoring_smoke import _restrict_gigachat_scope
from service.domain.subagents.pdf_generation_runtime import (
 DocumentGenerationRun,create_document_project,_write_authored_source,publication_artifacts)
stage='intent'; build_state=None; rejection='none'
async def main():
 global stage,build_state,rejection
 p=json.load(sys.stdin); ref=p['workspace_ref']
 brief=literal_shortcut('Создай PDF с текстом "'+p['literal']+'"'); assert brief is not None
 assert brief.literal_text==p['literal']
 with use_run_execution(PrivateRunResources.from_request(workspace_ref=ref)) as execution:
  stage='admission'
  await initialize_run_provider_admission(execution); _restrict_gigachat_scope(execution)
  stage='project'
  path,scaffold=await create_document_project(ref,brief)
  run=DocumentGenerationRun(ref=ref,brief=brief,model='GigaChat-2',
   project_path=path,scaffold_source=scaffold)
  stage='render'
  authored=await run._author(execution=execution)
  rejection=next((x for x in run.diagnostics if x in {
   'invalid_source','authoring_unsupported','evidence_required','citation_unknown'}),'none')
  assert authored is not None
  stage='source'
  await _write_authored_source(ref,path,authored)
  stage='compile'
  status=await run._compile(final=True)
  build_state=status.get('state') if status.get('state') in {
   'failed','cancelled','visual_pending','ready','preview_ready'} else 'unknown'
  assert status.get('state')=='visual_pending'
  assert execution.usage.project_since(0)['total']==0
  artifacts=publication_artifacts(status,initial_status='pending_audit')
  assert any(x.get('role')=='pdf' for x in artifacts)
  print(json.dumps({'descriptors':artifacts,'compile_state':'visual_pending'}))
try: asyncio.run(main())
except BaseException as error:
 trace=error.__traceback__
 while trace and trace.tb_next: trace=trace.tb_next
 filename=trace.tb_frame.f_code.co_filename.rsplit('/',1)[-1] if trace else ''
 component={'rendering.py':'rendering','draft.py':'draft',
  'pdf_generation_runtime.py':'runtime','<string>':'fixture'}.get(filename,'other')
 print(json.dumps({'failure':'compile_fixture_failed','stage':stage,'build_state':build_state,
  'rejection':rejection,'component':component,'line':trace.tb_lineno if trace else 0}))
 raise SystemExit(1)
"""

_DELIVER = """
import asyncio,json,logging,sys,uuid
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import config
from service.composition.container import build_container
from service.infrastructure import provider_policy_store as policy
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.chat.persistence.documents import publication as jobs
from service.services.chat.application.documents.publication.service import deliver_one
async def main():
 p=json.load(sys.stdin); c=build_container(config); stage='setup'; row_ids=[]
 try:
  await runtime_settings.refresh(force=True); await policy.prime()
  original=policy.disabled_providers
  # Only this short-lived fixture process is narrowed; no DB/settings mutation.
  policy.disabled_providers=lambda:set(original())|{'openai','openrouter','routerai','mws'}
  owner=await c.repositories.profile_repository.fetch_user_by_email(
   's38-video-acceptance@example.com'); assert owner is not None
  await c.services.chat_application_service.ensure_thread_owner(p['thread_id'],str(owner.id))
  before=await c.services.billing_service.get_balance(str(owner.id))
  billing_key='s37-gigachat-vision-'+uuid.uuid4().hex
  stage='enqueue'
  async with c.infra.pg_connector.get_session_context() as session:
   rows=await jobs.enqueue(session,user_id=owner.id,thread_id=p['thread_id'],
    workspace_id=p['workspace_id'],billing_job_id=billing_key,
    descriptors=jobs.normalize_descriptors(p['descriptors']),attach_to_latest=False,
    initial_status='pending_audit')
   row_ids=[x['id'] for x in rows]; assert row_ids
   claimed=await jobs.claim(session,limit=len(rows))
   assert {x['id'] for x in claimed}==set(row_ids)
   # Enqueue and lease acquisition commit together, so another worker cannot
   # audit this fixture with its wider policy between those two operations.
   await session.commit()
  outcomes=[]; stage='audit_delivery'
  for row in claimed:
   async with c.infra.pg_connector.get_session_context() as session:
    outcome=await deliver_one(config=config,pg_connector=c.infra.pg_connector,
     redis=c.infra.redis_client,file_service=c.services.file_saver_service,
     session=session,row=row)
    await session.commit(); outcomes.append(outcome)
  stage='delivery_replay'
  for _ in range(2):
   for row in claimed:
    async with c.infra.pg_connector.get_session_context() as session:
     outcome=await deliver_one(config=config,pg_connector=c.infra.pg_connector,
      redis=c.infra.redis_client,file_service=c.services.file_saver_service,
      session=session,row=row)
     assert outcome=='delivered'; await session.commit()
  stage='financial_verification'
  async with c.infra.pg_connector.get_session_context() as session:
   events=(await session.execute(text("SELECT metadata FROM profile.billing_events "
    "WHERE user_id=:owner AND event_type='usage' AND metadata->>'idempotency_key' "
    "LIKE :prefix"),{'owner':owner.id,'prefix':billing_key+':document-audit:%'})).scalars().all()
   calls=[call for event in events for call in event.get('per_call',[])]
   assert calls and all(x.get('provider')=='gigachat' for x in calls)
   assert all(x.get('kind')=='document_visual_audit' for x in calls)
   delivered=(await session.execute(text("SELECT role,user_file_id,artifact_sha256 "
    "FROM profile.document_publication_job WHERE billing_job_id=:key AND status='delivered'"),
    {'key':billing_key})).mappings().all()
   pdf=next((dict(x) for x in delivered if x['role']=='pdf'),None)
  after=await c.services.billing_service.get_balance(str(owner.id))
  async with c.infra.pg_connector.get_session_context() as session:
   audits=(await session.execute(text('SELECT a.state,a.charge_id,a.usage_envelope '
    'FROM profile.document_audit_attempt a JOIN profile.document_publication_job j '
    'ON j.id=a.publication_job_id WHERE j.billing_job_id=:key'),
    {'key':billing_key})).mappings().all()
   assert len(audits)==1 and audits[0]['state']=='settled' and audits[0]['charge_id']
   journal=audits[0]['usage_envelope']['_audit_usage_journal']
   assert len(journal['receipts'])==1 and journal['receipts'][0]['provider']=='gigachat'
   assert journal['receipts'][0]['kind']=='document_visual_audit'
  assert all(x=='delivered' for x in outcomes) and pdf
  assert len(events)==1 and len(calls)==1
  print(json.dumps({'file_id':str(pdf['user_file_id']),'sha256':pdf['artifact_sha256'],
   'provider':'gigachat','models':sorted({x['model'] for x in calls}),
   'receipts':len(calls),'charges':len(events),'delivered':len(delivered),
   'balance_before':before.total,'balance_after':after.total,
   'spent':before.total-after.total,'delivery_replays':2,'checkpoint_verified':True}))
 except BaseException:
  # Never leave a wider-policy maintenance worker a pending acceptance audit.
  if row_ids:
   async with c.infra.pg_connector.get_session_context() as session:
    for identity in row_ids:
     await session.execute(text("UPDATE profile.document_publication_job SET status='terminal',"
      "failure_code='unavailable',lease_token=NULL,lease_expires_at=NULL "
      "WHERE id=:id AND status IN ('pending_audit','pending_delivery')"),{'id':identity})
    await session.commit()
  print(json.dumps({'failure':stage})); raise
 finally:
  if c.infra.redis_manager: await c.infra.redis_manager.close()
  await c.infra.pg_connector.close()
try: asyncio.run(main())
except BaseException: raise SystemExit(1)
"""

_REPLAY = """
import asyncio,json,logging
logging.disable(logging.CRITICAL)
from sqlalchemy import text
from service.settings import config
from service.composition.container import build_container
async def main():
 c=build_container(config); pg=c.infra.pg_connector
 try:
  owner=await c.repositories.profile_repository.fetch_user_by_email(
   's38-video-acceptance@example.com'); assert owner is not None
  async with pg.get_session_context() as s:
   pdf=(await s.execute(text("SELECT j.billing_job_id FROM profile.document_publication_job j "
    "JOIN profile.\\\"user\\\" u ON u.id=j.user_id WHERE u.email=:email AND j.role='pdf' "
    "AND j.status='delivered' AND j.billing_job_id LIKE :prefix ORDER BY j.created_at DESC "
    "LIMIT 1"),{'email':'s38-video-acceptance@example.com',
    'prefix':'s37-gigachat-vision-%'})).scalar_one()
   rows=(await s.execute(text("SELECT role,user_file_id,artifact_sha256,mime_type "
    "FROM profile.document_publication_job WHERE billing_job_id=:key AND status='delivered'"),
    {'key':pdf})).mappings().all()
   events=(await s.execute(text("SELECT metadata FROM profile.billing_events WHERE "
    "metadata->>'idempotency_key' LIKE :prefix"),
    {'prefix':pdf+':document-audit:%'})).scalars().all()
   calls=[x for e in events for x in e.get('per_call',[])]
   assert len(events)==1 and len(calls)==1 and calls[0].get('provider')=='gigachat'
   digests=(await s.execute(text("SELECT j.artifact_sha256 "
    "FROM profile.document_publication_job j JOIN profile.\\\"user\\\" u ON u.id=j.user_id "
    "WHERE u.email=:email AND j.status='delivered' AND j.role='pdf' "
    "AND j.billing_job_id LIKE :prefix ORDER BY j.created_at DESC LIMIT 2"),
    {'email':'s38-video-acceptance@example.com','prefix':'s37-gigachat-vision-%'})).scalars().all()
   assert len(digests)==2 and len(set(digests))==2
  for artifact in rows:
   owned=await c.repositories.file_repository.fetch_user_file_by_id(
    owner.id,artifact['user_file_id'])
   # stat stays private: never return object keys or storage metadata.
   assert owned is not None
   stat=await asyncio.to_thread(c.infra.storage._client.stat_object,
    c.infra.storage._bucket,owned.file_name)
   assert stat.content_type==artifact['mime_type']
  print(json.dumps({'files':[{'role':x['role'],'file_id':str(x['user_file_id']),
   'sha256':x['artifact_sha256'],'mime_type':x['mime_type']} for x in rows],
   'provider':'gigachat','model':calls[0]['model'],'receipts':1,'charges':1,
   'stored_types_verified':True,'distinct_pdf_digests':True}))
 finally:
  if c.infra.redis_manager: await c.infra.redis_manager.close()
  await pg.close()
try: asyncio.run(main())
except BaseException: print(json.dumps({'failure':'financial_verification'})); raise SystemExit(1)
"""

_CLEANUP = """
import asyncio,json,logging,sys,httpx
logging.disable(logging.CRITICAL)
from service.settings import config
from service.composition.container import build_container
from service.infrastructure.workspace_client import read_binding,release_workspace,_config
async def main():
 p=json.load(sys.stdin); c=build_container(config)
 try:
  owner=await c.repositories.profile_repository.fetch_user_by_email(
   's38-video-acceptance@example.com'); assert owner is not None
  await c.services.chat_application_service.ensure_thread_owner(p['thread_id'],str(owner.id))
  ref=await read_binding(c.infra.redis_client,p['thread_id'])
  if ref:
   assert str(ref.get('user_id'))==str(owner.id)
   assert await release_workspace(c.infra.redis_client,p['thread_id'])
   _,base,timeout,key,_=_config(); assert base
   async with httpx.AsyncClient(timeout=timeout,trust_env=False) as client:
    r=await client.post(base+'/workspaces/'+ref['workspace_id']+'/view',
     json={'user_id':str(owner.id),'token':ref['token']},
     headers={'Authorization':'Bearer '+key})
    assert r.status_code in {404,410}
  assert await read_binding(c.infra.redis_client,p['thread_id']) is None
  print(json.dumps({'cleaned':True}))
 finally:
  if c.infra.redis_manager: await c.infra.redis_manager.close()
  await c.infra.pg_connector.close()
try: asyncio.run(main())
except BaseException: print(json.dumps({'failure':'cleanup_failed'})); raise SystemExit(1)
"""


def test_private_probe_programs_are_syntax_valid():
    for source in (_TOKEN, _SETUP, _BUILD, _DELIVER, _REPLAY, _CLEANUP):
        ast.parse(source)


def test_fixture_token_is_short_lived_read_only_and_fixed_to_the_dev_owner():
    assert "s38-video-acceptance@example.com" in _TOKEN
    assert "'jwt_exp_hours':1" in _TOKEN
    assert not any(word in _TOKEN for word in ("INSERT", "UPDATE", "DELETE", "create_session"))


async def _private_probe(container: str, source: str, payload: dict, timeout: int) -> dict:
    wrapper = "import io,sys; p=sys.stdin.read(); sys.stdin=io.StringIO(p); " + f"exec({source!r})"
    result = await asyncio.to_thread(
        subprocess.run,
        [
            "docker",
            "exec",
            "-i",
            "-e",
            "GIGACHAT_SMOKE_MODEL=GigaChat-2",
            container,
            "python",
            "-c",
            wrapper,
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    try:
        decoded = json.loads(result.stdout)
    except (ValueError, TypeError):
        pytest.fail("private_probe_protocol")
    if result.returncode:
        code = decoded.get("failure")
        assert code in {
            "setup_failed",
            "compile_fixture_failed",
            "setup",
            "enqueue",
            "audit_delivery",
            "delivery_replay",
            "financial_verification",
            "cleanup_failed",
            "fixture_auth_unavailable",
        }, "private_probe_failed"
        stage = decoded.get("stage")
        if stage in {"intent", "admission", "project", "render", "source", "compile"}:
            code += ":" + stage
        component = decoded.get("component")
        if component in {"rendering", "draft", "runtime", "fixture", "other"}:
            code += ":" + component + ":" + str(int(decoded.get("line") or 0))
        pytest.fail("private_probe_failed:" + code)
    return decoded


async def _fixture_credentials() -> dict:
    root = Path(__file__).resolve().parents[2]
    anchor = json.loads((root / ".env.s38").read_text())
    assert anchor["email"] == "s38-video-acceptance@example.com"
    fresh = await _private_probe("gpthub-dev-backend-1", _TOKEN, {}, 30)
    assert isinstance(fresh.get("token"), str) and fresh["token"], "fixture_auth_unavailable"
    return {"email": anchor["email"], "token": fresh["token"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "literal",
    [pytest.param("тест", id="literal_first"), pytest.param("тест 2", id="literal_second")],
)
@pytest.mark.skipif(
    os.getenv("S37_LIVE_GIGACHAT_LITERAL_AUDIT") != "1",
    reason="explicit metered GigaChat-only component acceptance",
)
async def test_literal_compiles_audits_settles_and_downloads_with_gigachat_only(literal):
    credentials = await _fixture_credentials()
    assert credentials["email"] == "s38-video-acceptance@example.com"
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": credentials["token"]}, timeout=30
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 GigaChat vision delivery"})
        assert created.status_code == 201, "owned_thread_create_failed"
        thread_id = created.json()["thread_id"]
        try:
            private = await _private_probe(
                "gpthub-dev-backend-1", _SETUP, {"thread_id": thread_id, "literal": literal}, 60
            )
            built = await _private_probe("gpthub-dev-agents-1", _BUILD, private, 180)
            report = await _private_probe(
                "gpthub-dev-backend-1",
                _DELIVER,
                {
                    "thread_id": thread_id,
                    "workspace_id": private["workspace_ref"]["workspace_id"],
                    "descriptors": built["descriptors"],
                },
                240,
            )
            response = await client.get(
                f"/api/service/files/v1/{report['file_id']}/download", follow_redirects=True
            )
            assert response.status_code == 200, "authenticated_download_failed"
            assert response.headers.get("content-type", "").startswith("application/pdf")
            assert hashlib.sha256(response.content).hexdigest() == report["sha256"]
            await asyncio.to_thread(_inspect_pdf, response.content, literal)
            assert report["receipts"] == report["charges"] == 1
            # Output only aggregate financial/provider evidence; keep credentials,
            # private references and artifact identifiers out of test output.
            print(json.dumps({k: v for k, v in report.items() if k not in {"file_id", "sha256"}}))
        finally:
            try:
                await _private_probe("gpthub-dev-backend-1", _CLEANUP, {"thread_id": thread_id}, 60)
            finally:
                removed = await client.delete(f"/api/chats/{thread_id}")
                assert removed.status_code in {200, 204}, "owned_thread_cleanup_failed"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_GIGACHAT_DOWNLOAD_REPLAY") != "1",
    reason="read-only replay of the previously metered GigaChat artifact",
)
async def test_existing_gigachat_pdf_and_bundle_download_without_another_charge():
    credentials = await _fixture_credentials()
    assert credentials["email"] == "s38-video-acceptance@example.com"
    report = await _private_probe("gpthub-dev-backend-1", _REPLAY, {}, 60)
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": credentials["token"]},
        timeout=30,
    ) as client:
        before = await client.get("/api/billing/balance")
        assert before.status_code == 200, "owned_balance_unavailable"
        roles = set()
        pdf_payload = None
        expected_literal = None
        for artifact in report["files"]:
            response = await client.get(
                f"/api/service/files/v1/{artifact['file_id']}/download", follow_redirects=True
            )
            assert response.status_code == 200, "authenticated_download_failed"
            assert response.headers.get("content-type", "").split(";")[0] == artifact["mime_type"]
            assert hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
            roles.add(artifact["role"])
            if artifact["role"] == "pdf":
                pdf_payload = response.content
            else:
                with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                    assert bundle.testzip() is None, "source_bundle_corrupt"
                    assert any(name.endswith("main.tex") for name in bundle.namelist())
                    sources = [
                        bundle.read(name).decode("utf-8")
                        for name in bundle.namelist()
                        if name.endswith("literal_text.tex")
                    ]
                    assert len(sources) == 1, "literal_source_missing"
                    expected_literal = "тест 2" if "тест 2" in sources[0] else "тест"
                    assert expected_literal in sources[0], "literal_source_missing"
        assert pdf_payload is not None and expected_literal is not None
        await asyncio.to_thread(_inspect_pdf, pdf_payload, expected_literal)
        after = await client.get("/api/billing/balance")
        assert after.status_code == 200 and before.json()["total"] == after.json()["total"]
        assert roles == {"pdf", "source_bundle"}
        print(
            json.dumps(
                {
                    "provider": report["provider"],
                    "model": report["model"],
                    "receipts": 1,
                    "charges": 1,
                    "downloads": len(roles),
                    "balance_unchanged": True,
                    "balance": after.json()["total"],
                }
            )
        )


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_GIGACHAT_DOWNLOAD_REPLAY") != "1",
    reason="owned fixture cleanup without inference",
)
async def test_private_workspace_fixture_cleanup_is_owner_checked_and_verified():
    credentials = await _fixture_credentials()
    assert credentials["email"] == "s38-video-acceptance@example.com"
    async with httpx.AsyncClient(
        base_url="http://localhost:8001", cookies={"auth_token": credentials["token"]}, timeout=30
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 cleanup fixture"})
        assert created.status_code == 201, "owned_thread_create_failed"
        thread_id = created.json()["thread_id"]
        try:
            await _private_probe(
                "gpthub-dev-backend-1", _SETUP, {"thread_id": thread_id, "literal": "тест"}, 60
            )
            assert await _private_probe(
                "gpthub-dev-backend-1", _CLEANUP, {"thread_id": thread_id}, 60
            ) == {"cleaned": True}
        finally:
            removed = await client.delete(f"/api/chats/{thread_id}")
            assert removed.status_code in {200, 204}, "owned_thread_cleanup_failed"
