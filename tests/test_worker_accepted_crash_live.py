"""Opt-in real SQL/broker recovery; model, billing and message writes are scripted."""

import ast
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,json,logging,os,signal,subprocess,sys,time,uuid
logging.disable(logging.CRITICAL)
folder=sys.argv[1]; sys.path.insert(0,folder)
os.environ['PYTHONPATH']=folder+os.pathsep+os.environ.get('PYTHONPATH','/dude')
from sqlalchemy import text
from service.settings import Config
from service.infrastructure.database.postgresql import PgConnector
from service.infrastructure.messaging.celery_app import celery_app
from service.models.db.db_models import UserLaunch
from service.models.key_value import ProcessingStatus,ServiceType
from s37_accepted_result_crash_fixture import accepted_with_crash
identity=uuid.uuid4().hex; marker='s37:accepted:'+identity
queue='s37-accepted-'+identity; hostname=queue+'@acceptance'
job=uuid.uuid4(); owner=None; worker=None; result=None; stage='fixture'
async def create():
 global owner
 c=PgConnector(Config().pg)
 try:
  async with c.get_session_context() as db:
   owner=await db.scalar(text('SELECT id FROM profile."user" WHERE email=:email'),
    {'email':'s37-e2e-391e5206659a3654@example.com'})
   assert owner is not None
   db.add(UserLaunch(id=job,user_id=owner,type=ServiceType.CHAT,
    status=ProcessingStatus.PROCESSING,payload={'thread_id':str(uuid.UUID(identity)),
     'fixture_marker':marker,'request':'synthetic'}))
   await db.commit()
 finally: await c.close()
async def billing_count():
 c=PgConnector(Config().pg)
 try:
  async with c.get_session_context() as db:
   return await db.scalar(text('SELECT count(*) FROM profile.billing_events '
    'WHERE user_id=:owner'),{'owner':owner})
 finally: await c.close()
async def cleanup():
 if owner is None: return
 c=PgConnector(Config().pg)
 try:
  async with c.get_session_context() as db:
   await db.execute(text('DELETE FROM profile.user_launch WHERE id=:id AND user_id=:owner '
    "AND payload->>'fixture_marker'=:marker"),{'id':job,'owner':owner,'marker':marker})
   await db.commit()
   assert await db.scalar(text('SELECT count(*) FROM profile.user_launch WHERE id=:id'),
    {'id':job})==0
 finally: await c.close()
report={'status':'failed','stage':stage}
try:
 asyncio.run(create()); before=asyncio.run(billing_count()); stage='worker_start'
 worker=subprocess.Popen([sys.executable,'-m','celery','-A',
  'service.infrastructure.messaging.celery_app','worker','--pool=prefork','--concurrency=1',
  '--queues='+queue,'--hostname='+hostname,'--include=s37_accepted_result_crash_fixture',
  '--loglevel=WARNING','--without-gossip','--without-mingle','--without-heartbeat'],
  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 deadline=time.monotonic()+45
 while not celery_app.control.ping(destination=[hostname],timeout=1):
  assert worker.poll() is None and time.monotonic()<deadline
  time.sleep(.5)
 stage='redelivery'
 result=accepted_with_crash.apply_async(queue=queue,kwargs={'job_id':str(job),'marker':marker})
 outcome=result.get(timeout=120)
 assert outcome=={'status':'resumed','attempts':2,'redelivered':True,
  'scripted_acceptances':1,'settlement_callbacks':1,'persist_callbacks':1}
 stage='billing_invariance'; assert asyncio.run(billing_count())==before
 report={'status':'passed',**outcome,'billing_events_unchanged':True}
 report['status']='passed'
except Exception:
 report={'status':'failed','stage':stage}
 line=celery_app.backend.client.get(marker+':failure-line')
 if line is not None: report['fixture_line']=int(line)
finally:
 try:
  if worker is not None and worker.poll() is None:
   os.killpg(worker.pid,signal.SIGTERM)
   try: worker.wait(timeout=10)
   except subprocess.TimeoutExpired: os.killpg(worker.pid,signal.SIGKILL); worker.wait(timeout=10)
  if result is not None: result.forget()
  asyncio.run(cleanup())
  client=celery_app.backend.client
  for suffix in ('',':scripted-acceptances',':settlements',':persist-callbacks',':first-pid',
   ':failure-line'):
   client.delete(marker+suffix)
  assert not list(client.scan_iter(match=marker+'*'))
  with celery_app.connection_for_write() as connection:
   connection.default_channel.queue_delete(queue)
  client.delete('_kombu.binding.'+queue)
 except Exception:
  report={'status':'failed','stage':'cleanup'}
print(json.dumps(report))
if report['status']!='passed': raise SystemExit(1)
"""


def test_accepted_crash_probe_compiles_without_side_effects():
    ast.parse(_PROBE)
    ast.parse(Path(__file__).with_name("accepted_result_crash_fixture.py").read_text("utf-8"))


@pytest.mark.skipif(
    os.getenv("S37_LIVE_ACCEPTED_CRASH") != "1", reason="isolated dev SQL/prefork acceptance"
)
def test_accepted_result_survives_real_prefork_loss():
    container = "gpthub-dev-backend-1"

    def command(*args, **kwargs):
        return subprocess.run(["docker", *args], capture_output=True, check=False, **kwargs)

    made = command("exec", container, "mktemp", "-d", "/tmp/s37-accepted-XXXXXXXX", timeout=15)
    folder = made.stdout.decode().strip()
    assert made.returncode == 0 and re.fullmatch(r"/tmp/s37-accepted-[A-Za-z0-9]{8}", folder)
    try:
        copied = command(
            "cp",
            str(Path(__file__).with_name("accepted_result_crash_fixture.py")),
            container + ":" + folder + "/s37_accepted_result_crash_fixture.py",
            timeout=15,
        )
        assert copied.returncode == 0, "accepted_fixture_copy_failed"
        result = command(
            "exec",
            "-i",
            container,
            "python",
            "-",
            folder,
            input=_PROBE.encode(),
            timeout=210,
        )
    finally:
        removed = command("exec", container, "rm", "-r", "--", folder, timeout=15)
        absent = command("exec", container, "test", "!", "-e", folder, timeout=15)
        assert removed.returncode == absent.returncode == 0, "accepted_fixture_cleanup_failed"
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "bounded_accepted_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, (
        f"accepted_crash_failed_at_{report.get('stage', 'unknown')}"
        f"_fixture_line_{report.get('fixture_line', 0)}"
    )
    assert report["billing_events_unchanged"] and report["redelivered"]
