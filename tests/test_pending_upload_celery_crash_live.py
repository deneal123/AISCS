"""Kill only an owned prefork child after an actual isolated S3 inventory read."""

import ast
import asyncio
import json
import os

import pytest

from tests.test_direct_upload_live import _run_minio_probe
from tests.test_pending_upload_celery_live import _MODULES, _PROBE

_INSTRUMENTATION = r"""
import asyncio,json,os
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
original_page=MinioFileStorage.pending_upload_page
async def pause_after_inventory(self,*args,**kwargs):
 page=await original_page(self,*args,**kwargs)
 marker=os.environ.get('S37_CRASH_MARKER')
 if marker:
  descriptor=os.open(marker+'.attempts',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
  try:
   os.write(descriptor,(json.dumps({'pid':os.getpid()})+'\n').encode()); os.fsync(descriptor)
  finally: os.close(descriptor)
  try: descriptor=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  except FileExistsError: return page
  try:
   os.write(descriptor,json.dumps({'pid':os.getpid()}).encode()); os.fsync(descriptor)
  finally: os.close(descriptor)
  await asyncio.sleep(90)
 return page
MinioFileStorage.pending_upload_page=pause_after_inventory
"""

_CRASH_ROUND = r"""
 stage='crash_worker_start'; stop()
 import tempfile
 crash_directory=Path(tempfile.mkdtemp(prefix='gpthub-retention-crash-'+identity.hex+'-'))
 crash_marker=crash_directory/'inventory-read.json'
 crash_environment={**environment,'S37_CRASH_MARKER':str(crash_marker)}
 third=start(crash_environment)
 assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
 stage='crash_inventory_read'
 result=app.send_task(name,queue=queue,task_id=str(uuid.uuid5(identity,'crash-task')))
 results.append(result)
 deadline=time.monotonic()+15
 while not crash_marker.exists():
  assert worker.poll() is None and time.monotonic()<deadline
  time.sleep(.1)
 recorded=json.loads(crash_marker.read_text())
 assert recorded=={'pid':third[1]} and third[1]>1
 assert not result.ready()
 stats=app.control.inspect(destination=[hostname],timeout=2).stats()
 assert stats[hostname]['pool']['processes']==[third[1]]
 stage='prefork_child_kill'; os.kill(third[1],signal.SIGKILL)
 stage='native_task_redelivery'
 assert result.get(timeout=45)==expected and worker.poll() is None
 stats=app.control.inspect(destination=[hostname],timeout=2).stats()
 replacement=stats[hostname]['pool']['processes']
 assert len(replacement)==1 and replacement[0]!=third[1]
 lines=Path(str(crash_marker)+'.attempts').read_text().splitlines()
 attempts=[json.loads(line) for line in lines]
 assert attempts==[{'pid':third[1]},{'pid':replacement[0]}]
 assert json.loads(crash_marker.read_text())==recorded
 loop.run_until_complete(check())
"""

_CRASH_CLEANUP = r"""
def remove_crash_fixture():
 if crash_directory is None: return
 assert crash_directory.name.startswith('gpthub-retention-crash-'+identity.hex+'-')
 assert crash_marker.parent==crash_directory and crash_marker.name=='inventory-read.json'
 Path(str(crash_marker)+'.attempts').unlink(missing_ok=True)
 crash_marker.unlink(missing_ok=True); crash_directory.rmdir()
 assert not crash_directory.exists()
"""


def _crash_probe():
    """Keep the native task/fixture unchanged except explicit local fault boundaries."""
    replacements = (
        (
            "worker=None; storage=None; manager=None; results=[]; cache=None",
            "worker=None; storage=None; manager=None; results=[]; cache=None; "
            "crash_directory=None; crash_marker=None",
        ),
        (
            "from service.infrastructure.messaging.celery_app import celery_app\n"
            "celery_app.worker_main",
            "from service.infrastructure.messaging.celery_app import celery_app\n"
            + _INSTRUMENTATION
            + "\ncelery_app.worker_main",
        ),
        (
            " loop.run_until_complete(check()); scheduler.close()",
            " loop.run_until_complete(check()); scheduler.close()\n" + _CRASH_ROUND,
        ),
        (
            "  'native_schedule_delivered':True}",
            "  'native_schedule_delivered':True,'child_loss_redelivered':True,"
            "'two_inventory_attempts':True}",
        ),
        (
            "report={'status':'failed','stage':stage}\ntry:",
            _CRASH_CLEANUP + "\nreport={'status':'failed','stage':stage}\ntry:",
        ),
        (
            "  ('worker',stop),('results',forget_results),('broker',remove_broker_fixture),",
            "  ('worker',stop),('crash_marker',remove_crash_fixture),"
            "('results',forget_results),('broker',remove_broker_fixture),",
        ),
    )
    probe = _PROBE
    for original, replacement in replacements:
        assert probe.count(original) == 1, "retention_crash_fixture_contract_changed"
        probe = probe.replace(original, replacement, 1)
    return probe


def test_crash_probe_preserves_native_fixture_contract_and_compiles():
    probe = _crash_probe()
    ast.parse(probe)
    ast.parse(_INSTRUMENTATION)
    assert "page=await original_page" in probe
    assert probe.index("page=await original_page") < probe.index("descriptor=os.open")
    assert "os.kill(third[1],signal.SIGKILL)" in probe
    assert "killpg(third" not in probe
    assert "result.get(timeout=45)==expected" in probe
    assert "replacement[0]!=third[1]" in probe
    assert "('crash_marker',remove_crash_fixture)" in probe


@pytest.mark.asyncio
async def test_fault_boundary_reads_inventory_and_pauses_only_first_attempt(monkeypatch, tmp_path):
    from service.infrastructure.storage.minio_file_storage import MinioFileStorage

    marker = tmp_path / "inventory-read.json"
    monkeypatch.setenv("S37_CRASH_MARKER", str(marker))
    observed = []
    page = object()

    async def read_inventory(self, *args, **kwargs):
        assert args == ("uploads/CHAT/pending/", None, 128)
        assert kwargs == {}
        observed.append("inventory")
        return page

    async def interrupt(seconds):
        assert seconds == 90
        observed.append("pause")
        raise asyncio.CancelledError

    monkeypatch.setattr(MinioFileStorage, "pending_upload_page", read_inventory)
    scope = {}
    exec(_INSTRUMENTATION, scope)
    monkeypatch.setattr(asyncio, "sleep", interrupt)
    hook = scope["pause_after_inventory"]
    with pytest.raises(asyncio.CancelledError):
        await hook(object(), "uploads/CHAT/pending/", None, 128)
    assert json.loads(marker.read_text()) == {"pid": os.getpid()}
    assert await hook(object(), "uploads/CHAT/pending/", None, 128) is page
    assert observed == ["inventory", "pause", "inventory"]
    assert [
        json.loads(line) for line in marker.with_suffix(".json.attempts").read_text().splitlines()
    ] == [
        {"pid": os.getpid()},
        {"pid": os.getpid()},
    ]


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PENDING_CRASH") != "1", reason="owned prefork SIGKILL/isolated MinIO"
)
def test_native_retention_redelivered_after_owned_child_loss():
    _run_minio_probe(
        real_persistence=True,
        probe=_crash_probe(),
        modules=_MODULES,
        probe_timeout=240,
        expected_report={
            "status": "passed",
            "native_task_delivered": True,
            "prefork_restarted": True,
            "result_survived_restart": True,
            "cursor_persisted": True,
            "fresh_and_private_preserved": True,
            "native_schedule_delivered": True,
            "child_loss_redelivered": True,
            "two_inventory_attempts": True,
        },
    )
