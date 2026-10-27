"""Native retention redelivery after real S3 deletion, before durable cursor write."""

import ast
import asyncio
import json
import os

import pytest

from tests.test_direct_upload_live import _run_minio_probe
from tests.test_pending_upload_celery_crash_live import (
    _CRASH_ROUND,
    _INSTRUMENTATION,
    _crash_probe,
)
from tests.test_pending_upload_celery_live import _MODULES

_DELETE_INSTRUMENTATION = r"""
import asyncio,json,os
from datetime import UTC,datetime,timedelta
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application import pending_upload_cleanup as cleanup_module
original_page=MinioFileStorage.pending_upload_page
original_delete=MinioFileStorage.delete_file
original_cleanup=cleanup_module.cleanup_pending_uploads
async def record_inventory(self,*args,**kwargs):
 page=await original_page(self,*args,**kwargs)
 marker=os.environ.get('S37_CRASH_MARKER')
 if marker:
  descriptor=os.open(marker+'.attempts',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
  try:
   os.write(descriptor,(json.dumps({'pid':os.getpid()})+'\n').encode()); os.fsync(descriptor)
  finally: os.close(descriptor)
 return page
async def pause_after_delete(self,*args,**kwargs):
 result=await original_delete(self,*args,**kwargs)
 marker=os.environ.get('S37_CRASH_MARKER')
 if marker:
  assert kwargs['file_key'].startswith('uploads/CHAT/pending/')
  descriptor=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  try:
   os.write(descriptor,json.dumps({'pid':os.getpid()}).encode()); os.fsync(descriptor)
  finally: os.close(descriptor)
  await asyncio.sleep(90)
 return result
async def fixture_retention_clock(**kwargs):
 if os.environ.get('S37_CRASH_MARKER'):
  return await original_cleanup(now=datetime.now(UTC)+timedelta(days=2),**kwargs)
 return await original_cleanup(**kwargs)
MinioFileStorage.pending_upload_page=record_inventory
MinioFileStorage.delete_file=pause_after_delete
cleanup_module.cleanup_pending_uploads=fixture_retention_clock
"""


def _replace_once(probe, before, after):
    assert probe.count(before) == 1, "retention_delete_crash_fixture_contract_changed"
    return probe.replace(before, after, 1)


def _delete_crash_probe():
    round_body = _replace_once(
        _CRASH_ROUND,
        " stage='crash_worker_start'; stop()",
        " stage='crash_worker_start'; stop()\n"
        " loop.run_until_complete(cache.invalidate('file_upload_cleanup','CHAT'))",
    )
    round_body = _replace_once(
        round_body,
        " stage='prefork_child_kill'; os.kill(third[1],signal.SIGKILL)",
        " stage='deleted_before_cursor'\n"
        " assert loop.run_until_complete(storage.pending_upload_stat(key)) is None\n"
        " assert loop.run_until_complete(cache.get_json('file_upload_cleanup','CHAT')) is None\n"
        " assert loop.run_until_complete(storage.get_file(private))==b'private'\n"
        " stage='prefork_child_kill'; os.kill(third[1],signal.SIGKILL)",
    )
    round_body = _replace_once(
        round_body,
        " assert result.get(timeout=45)==expected and worker.poll() is None",
        " recovered={'status':'success','scanned':0,'deleted':0,'skipped':0,'failed':0}\n"
        " assert result.get(timeout=45)==recovered and worker.poll() is None",
    )
    round_body = _replace_once(
        round_body,
        " loop.run_until_complete(check())",
        " assert loop.run_until_complete(storage.pending_upload_stat(key)) is None\n"
        " assert loop.run_until_complete(storage.get_file(private))==b'private'\n"
        " saved=loop.run_until_complete(cache.get_json('file_upload_cleanup','CHAT'))\n"
        " assert saved=={'cursor':None}",
    )
    probe = _replace_once(_crash_probe(), _INSTRUMENTATION, _DELETE_INSTRUMENTATION)
    probe = _replace_once(probe, _CRASH_ROUND, round_body)
    probe = probe.replace("inventory-read.json", "source-deleted.json")
    return _replace_once(
        probe,
        "'child_loss_redelivered':True,",
        "'child_loss_redelivered':True,'deleted_before_cursor_recovered':True,",
    )


def test_delete_crash_probe_has_native_deletion_and_compiles():
    probe = _delete_crash_probe()
    ast.parse(probe)
    ast.parse(_DELETE_INSTRUMENTATION)
    assert probe.index("result=await original_delete") < probe.index(
        "async def fixture_retention_clock"
    )
    assert "stage='deleted_before_cursor'" in probe
    assert "'scanned':0,'deleted':0,'skipped':0,'failed':0" in probe
    assert "assert attempts==[{'pid':third[1]},{'pid':replacement[0]}]" in probe


@pytest.mark.asyncio
async def test_delete_fault_boundary_pauses_after_commit_and_replay_reads_empty(
    monkeypatch, tmp_path
):
    from service.infrastructure.storage.minio_file_storage import MinioFileStorage
    from service.services.files.application import pending_upload_cleanup as cleanup

    marker = tmp_path / "source-deleted.json"
    monkeypatch.setenv("S37_CRASH_MARKER", str(marker))
    present = True
    observed = []

    async def read_inventory(self):
        observed.append("inventory")
        return ["source"] if present else []

    async def delete_source(self, *, file_key):
        nonlocal present
        assert file_key == "uploads/CHAT/pending/fixture.png"
        assert present
        present = False
        observed.append("committed_delete")

    async def interrupted(seconds):
        assert seconds == 90 and not present
        observed.append("pause")
        raise asyncio.CancelledError

    monkeypatch.setattr(MinioFileStorage, "pending_upload_page", read_inventory)
    monkeypatch.setattr(MinioFileStorage, "delete_file", delete_source)
    # Register restoration of the production cleanup function overwritten by exec.
    monkeypatch.setattr(cleanup, "cleanup_pending_uploads", cleanup.cleanup_pending_uploads)
    scope = {}
    exec(_DELETE_INSTRUMENTATION, scope)
    monkeypatch.setattr(asyncio, "sleep", interrupted)
    assert await scope["record_inventory"](object()) == ["source"]
    with pytest.raises(asyncio.CancelledError):
        await scope["pause_after_delete"](object(), file_key="uploads/CHAT/pending/fixture.png")
    assert await scope["record_inventory"](object()) == []
    assert json.loads(marker.read_text()) == {"pid": os.getpid()}
    assert observed == ["inventory", "committed_delete", "pause", "inventory"]


@pytest.mark.skipif(
    os.getenv("S37_LIVE_PENDING_DELETE_CRASH") != "1",
    reason="owned prefork loss after isolated S3 deletion/native SQL guard",
)
def test_native_retention_recovered_after_delete_before_cursor():
    _run_minio_probe(
        real_persistence=True,
        probe=_delete_crash_probe(),
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
            "deleted_before_cursor_recovered": True,
        },
    )
