"""Real Redis cancellation watcher composed with native SQL/storage settlement."""

import ast
import os

import pytest

from tests.test_direct_upload_live import _run_minio_probe
from tests.test_file_metadata_cancellation_live import _MODULES as _BASE_MODULES
from tests.test_file_metadata_cancellation_live import _PROBE as _BASE_PROBE

_MODULES = (
    *_BASE_MODULES,
    "service/services/chat/infrastructure/chat_worker/execution/cancellation.py",
    "service/services/chat/infrastructure/chat_worker/factory.py",
)


def _control_probe():
    """Reuse owned SQL/S3 fixture and cleanup; only change the cancellation source."""
    replacements = (
        (
            "from service.models.key_value import ServiceType",
            "from service.models.key_value import ServiceType\n"
            "from service.services.chat.infrastructure.chat_worker.execution.cancellation import "
            "CancelledByUser,run_with_cancel\n"
            "from service.services.chat.infrastructure.chat_worker.factory import "
            "ChatWorkerDependencyFactory",
        ),
        (
            "sys.modules[FileRepository.__module__],sys.modules[MinioFileStorage.__module__])",
            "sys.modules[FileRepository.__module__],sys.modules[MinioFileStorage.__module__],"
            "sys.modules[run_with_cancel.__module__],"
            "sys.modules[ChatWorkerDependencyFactory.__module__])",
        ),
        (
            "prefix='cancel-commit/'+identity+'/'",
            "prefix='cancel-commit/'+identity+'/'\n"
            " control=ChatWorkerDependencyFactory().create_redis_client(cfg); assert control\n"
            " keys=[]",
        ),
        (
            "raise asyncio.CancelledError('private-cancelled-commit-fixture')",
            "assert control.set('chat:cancel:'+control_id,'1',ex=30,nx=True)\n"
            "     await asyncio.Event().wait()",
        ),
        (
            "intent=uuid.uuid4(); intents.append(intent)",
            "intent=uuid.uuid4(); intents.append(intent)\n"
            "    control_id='s37-metadata-control-'+identity+'-'+intent.hex\n"
            "    keys.append('chat:cancel:'+control_id)",
        ),
        (
            "    try:\n     if streaming:",
            "    async def upload():\n     if streaming:",
        ),
        (
            "     raise AssertionError('cancellation_became_success')\n"
            "    except asyncio.CancelledError: pass",
            "    try:\n"
            "     await asyncio.wait_for(run_with_cancel(upload(),redis_client=control,\n"
            "      celery_task_id=control_id,poll_interval=.01),timeout=15)\n"
            "     raise AssertionError('cancellation_became_success')\n"
            "    except CancelledByUser: pass\n"
            "    assert control.get('chat:cancel:'+control_id) is None",
        ),
        (
            "  await connector.close()",
            "  try:\n"
            "   for key in keys:\n"
            "    assert key.startswith('chat:cancel:s37-metadata-control-'+identity+'-')\n"
            "    control.delete(key); assert control.get(key) is None\n"
            "  finally:\n"
            "   control.close(); await connector.close()",
        ),
        (
            "'rolled_back_compensated':2,'fixture_cleaned':True",
            "'rolled_back_compensated':2,'fixture_cleaned':True,'control_flags_consumed':4",
        ),
    )
    # This corpus exercises the four Redis-driven commit cases. The additional
    # direct task.cancel() fixture belongs to the base probe only, not to this
    # watcher composition. Keep its aggregate separate and fail on fixture drift.
    start = "  stage='post_upload_second_disconnect'\n"
    end = "  stage='inventory'\n"
    assert _BASE_PROBE.count(start) == _BASE_PROBE.count(end) == 1
    prefix, remainder = _BASE_PROBE.split(start, 1)
    _, suffix = remainder.split(end, 1)
    probe = prefix + end + suffix
    probe = probe.replace("'cancelled_calls':5", "'cancelled_calls':4", 1)
    probe = probe.replace("'post_upload_compensated':True,", "", 1)
    for before, after in replacements:
        assert probe.count(before) == 1, "metadata_control_fixture_drift"
        probe = probe.replace(before, after, 1)
    return probe


def test_control_probe_compiles_and_uses_native_watcher():
    probe = _control_probe()
    ast.parse(probe)
    assert "raise asyncio.CancelledError" not in probe
    assert "run_with_cancel(upload()" in probe
    assert "except CancelledByUser" in probe


@pytest.mark.skipif(
    os.getenv("S37_LIVE_METADATA_CANCEL_CONTROL") != "1",
    reason="real dev Redis/SQL + disposable MinIO",
)
def test_redis_user_cancel_settles_metadata_before_reporting_cancelled():
    _run_minio_probe(
        real_persistence=True,
        probe=_control_probe(),
        modules=_MODULES,
        probe_timeout=90,
        expected_report={
            "status": "passed",
            "cancelled_calls": 4,
            "committed_preserved": 2,
            "rolled_back_compensated": 2,
            "fixture_cleaned": True,
            "control_flags_consumed": 4,
        },
    )
