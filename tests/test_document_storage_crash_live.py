"""Opt-in metered authenticated build -> actual audit/stream/save -> prefork crash acceptance."""

import ast
import asyncio
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

_PROBE = """
import asyncio,json,logging,os,signal,subprocess,sys,time,uuid
logging.disable(logging.CRITICAL)
folder=sys.argv[1]; values=json.loads(sys.stdin.read()); sys.path.insert(0,folder)
os.environ['PYTHONPATH']=folder+os.pathsep+os.environ.get('PYTHONPATH','/dude')
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.services.chat.persistence.documents.publication import enqueue,normalize_descriptors
from service.services.chat.infrastructure.chat_worker.factory import build_file_service
from service.services.chat.infrastructure.chat_worker.factory import ChatWorkerDependencyFactory
from service.infrastructure.workspace_client import read_binding
from s37_document_storage_crash_fixture import deliver_with_storage_crash
identity=uuid.uuid4().hex; marker='s37:document-storage:'+identity
queue='s37-storage-'+identity; hostname=queue+'@acceptance'
worker=None; result=None; publication=None; owner=None; delivered=False; stage='fixture'
async def create():
 global publication,owner
 c=PgConnector(Config().pg)
 async with c.get_session_context() as db:
  owner=await db.scalar(text('SELECT t.user_id FROM profile.chat_threads t '
   'JOIN profile."user" u ON u.id=t.user_id WHERE t.thread_id=:thread AND u.email=:email'),
   {'thread':values['thread_id'],'email':'s37-e2e-391e5206659a3654@example.com'})
  assert owner is not None
  assert values['page_count']==1
  redis=ChatWorkerDependencyFactory().create_redis_client(Config())
  try:
   binding=await read_binding(redis,values['thread_id'])
   assert binding is not None
   values['workspace_id']=binding['workspace_id']
  finally: redis.close()
  descriptors=normalize_descriptors([values['artifact']]); assert len(descriptors)==1
  rows=await enqueue(db,user_id=owner,thread_id=values['thread_id'],
   workspace_id=values['workspace_id'],billing_job_id=marker,attach_to_latest=False,
   descriptors=descriptors,initial_status='pending_audit')
  publication=rows[0]['id']
  await db.execute(text("UPDATE profile.document_publication_job SET lease_token=:token,"
   "lease_expires_at=clock_timestamp()+interval '600 seconds',"
   "next_attempt_at=clock_timestamp()+interval '1 hour' WHERE id=:id"),
   {'token':uuid.uuid4(),'id':publication})
  await db.commit()
 await c.close()
async def verify():
 c=PgConnector(Config().pg)
 async with c.get_session_context() as db:
  row=(await db.execute(text('SELECT * FROM profile.document_publication_job '
   'WHERE id=:id AND user_id=:owner'),{'id':publication,'owner':owner})).mappings().one()
  assert row['status']=='delivered' and row['user_file_id']
  intent=uuid.uuid5(uuid.NAMESPACE_URL,
   f"gpthub-document:{owner}:{row['build_id']}:{row['artifact_id']}:{row['role']}")
  files=(await db.execute(text('SELECT id,content_sha256 FROM profile.user_file '
   'WHERE user_id=:owner AND upload_intent_id=:intent'),{'owner':owner,'intent':intent})).all()
  assert len(files)==1 and files[0][0]==row['user_file_id']
  assert files[0][1]==row['artifact_sha256']
  audits=(await db.execute(text('SELECT id,state,usage_envelope '
   'FROM profile.document_audit_attempt '
   'WHERE publication_job_id=:id'),{'id':publication})).mappings().all()
  assert len(audits)==1 and audits[0]['state']=='settled'
  usage=audits[0]['usage_envelope']; assert usage['total']>0 and len(usage['calls'])==1
  charge_key=marker+':document-audit:'+str(audits[0]['id'])
  events=(await db.execute(text("SELECT tokens,metadata FROM profile.billing_events "
   "WHERE user_id=:owner AND event_type='usage' AND metadata->>'idempotency_key'=:key"),
   {'owner':owner,'key':charge_key})).all()
  assert len(events)==1 and events[0][0]==usage['total']
  cost=events[0][1].get('from_subscription',0)+events[0][1].get('from_topup',0)
  assert cost>0
  return {'file_id':str(row['user_file_id']),'sha256':row['artifact_sha256'],
   'audit_model':usage['calls'][0]['model'],'tokens':usage['total'],'credits':cost,
   'single_audit_charge':True,'single_file':True,'reused':True}
async def cleanup():
 if publication is None: return
 c=PgConnector(Config().pg); lost_file=None
 async with c.get_session_context() as db:
  row=(await db.execute(text('SELECT build_id,artifact_id,role '
   'FROM profile.document_publication_job '
   'WHERE id=:id AND user_id=:owner AND billing_job_id=:marker'),
   {'id':publication,'owner':owner,'marker':marker})).mappings().first()
  if row and not delivered:
   intent=uuid.uuid5(uuid.NAMESPACE_URL,
    f"gpthub-document:{owner}:{row['build_id']}:{row['artifact_id']}:{row['role']}")
   lost_file=await db.scalar(text('SELECT id FROM profile.user_file '
    'WHERE user_id=:owner AND upload_intent_id=:intent'),{'owner':owner,'intent':intent})
  await db.execute(text('DELETE FROM profile.document_publication_job WHERE id=:id '
   'AND user_id=:owner AND billing_job_id=:marker'),
   {'id':publication,'owner':owner,'marker':marker}); await db.commit()
  assert await db.scalar(text('SELECT count(*) FROM profile.document_publication_job WHERE id=:id'),
   {'id':publication})==0
  assert await db.scalar(text('SELECT count(*) FROM profile.document_audit_attempt '
   'WHERE publication_job_id=:id'),{'id':publication})==0
 if lost_file: await build_file_service(Config(),c).delete(owner,lost_file)
 await c.close()
report={'status':'failed','stage':stage}
try:
 asyncio.run(create()); stage='worker_start'
 worker=subprocess.Popen([sys.executable,'-m','celery','-A',
  'service.infrastructure.messaging.celery_app','worker','--pool=prefork','--concurrency=1',
  '--queues='+queue,'--hostname='+hostname,'--include=s37_document_storage_crash_fixture',
  '--loglevel=WARNING','--without-gossip','--without-mingle','--without-heartbeat'],
  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 deadline=time.monotonic()+60
 while not celery_app.control.ping(destination=[hostname],timeout=1):
  assert worker.poll() is None and time.monotonic()<deadline
  time.sleep(.5)
 stage='delivery'
 result=deliver_with_storage_crash.apply_async(queue=queue,
  kwargs={'publication_id':str(publication),'marker':marker})
 assert result.get(timeout=300)=={
  'status':'delivered','attempts':2,'reused':True,'redelivered':True}
 stage='verification'; report={'status':'passed',**asyncio.run(verify())}; delivered=True
except Exception:
 report={'status':'failed','stage':stage}
finally:
 try:
  if worker is not None and worker.poll() is None:
   os.killpg(worker.pid,signal.SIGTERM)
   try: worker.wait(timeout=10)
   except subprocess.TimeoutExpired: os.killpg(worker.pid,signal.SIGKILL); worker.wait(timeout=10)
  if result is not None: result.forget()
  asyncio.run(cleanup())
  client=celery_app.backend.client
  for suffix in ('',':saves',':file-id',':first-pid'): client.delete(marker+suffix)
  assert not list(client.scan_iter(match=marker+'*'))
  with celery_app.connection_for_write() as connection:
   connection.default_channel.queue_delete(queue)
  client.delete('_kombu.binding.'+queue)
  assert not list(client.scan_iter(match='*'+queue+'*'))
 except Exception:
  report={'status':'failed','stage':'cleanup'}
print(json.dumps(report))
if report.get('status')!='passed': raise SystemExit(1)
"""


def test_storage_crash_probe_and_task_compile_without_running():
    ast.parse(_PROBE)
    ast.parse(Path(__file__).with_name("document_storage_crash_fixture.py").read_text("utf-8"))


async def _controller(values):
    def command(*args, **kwargs):
        return subprocess.run(["docker", *args], capture_output=True, check=False, **kwargs)

    made = await asyncio.to_thread(
        command,
        "exec",
        "gpthub-dev-backend-1",
        "mktemp",
        "-d",
        "/tmp/s37-storage-XXXXXXXX",
        timeout=15,
    )
    folder = made.stdout.decode().strip()
    assert made.returncode == 0 and re.fullmatch(r"/tmp/s37-storage-[A-Za-z0-9]{8}", folder)
    try:
        copied = await asyncio.to_thread(
            command,
            "cp",
            str(Path(__file__).with_name("document_storage_crash_fixture.py")),
            "gpthub-dev-backend-1:" + folder + "/s37_document_storage_crash_fixture.py",
            timeout=15,
        )
        assert copied.returncode == 0, "storage_fixture_copy_failed"
        # Values contain owned opaque identifiers and bounded artifact facts, never capabilities.
        wrapped = _PROBE.replace("values=json.loads(sys.stdin.read())", "values=" + repr(values))
        result = await asyncio.to_thread(
            command,
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-",
            folder,
            input=wrapped.encode(),
            timeout=390,
        )
    finally:
        removed = await asyncio.to_thread(
            command, "exec", "gpthub-dev-backend-1", "rm", "-r", "--", folder, timeout=15
        )
        absent = await asyncio.to_thread(
            command, "exec", "gpthub-dev-backend-1", "test", "!", "-e", folder, timeout=15
        )
        assert removed.returncode == absent.returncode == 0, "storage_fixture_cleanup_failed"
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "bounded_storage_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, f"storage_crash_failed_at_{report.get('stage', 'unknown')}"
    return report


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_STORAGE_CRASH") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
    reason="explicit metered vision and real storage/prefork acceptance",
)
async def test_audited_pdf_survives_storage_commit_crash_without_second_file_or_charge():
    from tests.test_literal_pdf_delivery_live import _inspect_pdf

    file_id = None
    async with httpx.AsyncClient(
        base_url="http://localhost:8001",
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        headers={"X-Workspace-Session": str(uuid4())},
        timeout=60,
    ) as client:
        created = await client.post("/api/chats/", json={"title": "S37 storage crash"})
        assert created.status_code == 201, "storage_thread_create_failed"
        thread = str(UUID(created.json()["thread_id"]))
        try:
            activated = await client.post(f"/api/chats/{thread}/work/activate")
            assert activated.status_code == 200, "storage_workspace_activate_failed"
            snapshot = activated.json()
            path = "documents/storage-crash"
            lease = await client.post(
                f"/api/chats/{thread}/workspace/leases/acquire", json={"path": path}
            )
            assert lease.status_code == 200, "storage_project_lease_failed"
            fence = lease.json()["fence"]
            project = await client.post(
                f"/api/chats/{thread}/workspace/documents",
                json={
                    "path": path,
                    "profile_id": "generic_document",
                    "locale": "ru-RU",
                    "mode": "camera_ready",
                    "expected_revision": snapshot["workspace"]["revision"],
                    "fence": fence,
                },
            )
            assert project.status_code == 200, "storage_scaffold_failed"
            source = "\n".join(
                [
                    r"\documentclass[11pt,a4paper]{article}",
                    r"\usepackage{fontspec}",
                    r"\setmainfont{DejaVu Serif}",
                    r"\usepackage[russian]{babel}",
                    r"\usepackage[margin=25mm]{geometry}",
                    r"\pagestyle{empty}",
                    r"\begin{document}",
                    "тест",
                    r"\end{document}",
                    "",
                ]
            )
            published = await client.post(
                f"/api/chats/{thread}/workspace/documents/source",
                json={
                    "path": path,
                    "files": {"main.tex": source},
                    "authoring_version": 1,
                    "draft_digest": hashlib.sha256(source.encode()).hexdigest(),
                    "expected_revision": project.json()["revision"],
                    "fence": fence,
                },
            )
            assert published.status_code == 200, "storage_source_publish_failed"
            started = await client.post(
                f"/api/chats/{thread}/workspace/documents/builds",
                json={
                    "path": path,
                    "expected_revision": published.json()["revision"],
                    "fence": fence,
                    "final": True,
                },
            )
            assert started.status_code == 200, "storage_build_start_failed"
            build = started.json()["build_id"]
            async with asyncio.timeout(120):
                while True:
                    status = await client.post(
                        f"/api/chats/{thread}/workspace/documents/builds/{build}", json={}
                    )
                    assert status.status_code == 200, "storage_build_status_failed"
                    value = status.json()
                    if value.get("state") in {"visual_pending", "failed", "cancelled"}:
                        break
                    await asyncio.sleep(1)
            if value["state"] != "visual_pending":
                allowed = {
                    "compile_failed",
                    "audit_failed",
                    "deterministic_audit_failed",
                    "runtime_unavailable",
                    "source_changed",
                    "artifact_invalid",
                    "source_invalid",
                    "build_interrupted",
                    "timeout",
                    "internal",
                }
                code = value.get("failure_code")
                diagnostic_codes = {
                    "pdf_invalid",
                    "orientation_mismatch",
                    "type3_font",
                    "font_not_embedded",
                    "undefined_reference",
                    "undefined_citation",
                    "multiply_defined",
                    "compile_error",
                    "missing_file",
                    "page_limit",
                    "page_size_mismatch",
                    "placeholder_unresolved",
                    "bibliography_missing",
                    "required_section_missing",
                }
                bounded = [
                    item["code"]
                    for item in value.get("diagnostics", [])
                    if item.get("severity") == "error" and item.get("code") in diagnostic_codes
                ]
                pytest.fail(
                    "storage_build_failed_"
                    + (code if code in allowed else "unknown")
                    + "_"
                    + ",".join(bounded)
                )
            pdf = next(
                item for item in value["artifacts"] if item["mime_type"] == "application/pdf"
            )
            # Read the owned binding only inside backend; browser snapshot never exposes it.
            report = await _controller(
                {
                    "thread_id": thread,
                    "workspace_id": "resolve-owned-binding",
                    "page_count": value["page_count"],
                    "artifact": {
                        **pdf,
                        "build_id": build,
                        "role": "pdf",
                        "source_digest": value["source_digest"],
                        "initial_status": "pending_audit",
                    },
                }
            )
            file_id = str(UUID(report["file_id"]))
            downloaded = await client.get(
                f"/api/service/files/v1/{file_id}/download",
                follow_redirects=True,
            )
            assert downloaded.status_code == 200, "storage_download_failed"
            assert hashlib.sha256(downloaded.content).hexdigest() == report["sha256"], (
                "storage_download_digest_failed"
            )
            await asyncio.to_thread(_inspect_pdf, downloaded.content, "тест")
            assert report["single_audit_charge"] and report["single_file"] and report["reused"]
        finally:
            if file_id:
                removed = await client.delete(f"/api/service/files/v1/delete/{file_id}")
                assert removed.status_code in {200, 204}, "storage_acceptance_file_cleanup_failed"
            deleted = await client.delete(f"/api/chats/{thread}")
            assert deleted.status_code in {200, 204}, "storage_acceptance_thread_cleanup_failed"
