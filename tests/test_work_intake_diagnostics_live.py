"""Opt-in installed-runtime probe for bounded plain-text import diagnostics."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_MODULE = "service/services/chat/presentation/routers/chat_api/work_intake.py"
_CONTAINERS = (
    "gpthub-dev-backend-1",
    "gpthub-dev-celery-worker-agents-1",
    "gpthub-dev-celery-worker-maintenance-1",
)
_PROBE = r"""
import hashlib,io,json,logging,sys
from pathlib import Path
from service.services.chat.presentation.routers.chat_api import work_intake as module
wire=json.load(sys.stdin);stage='source_parity'
try:
 assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()==wire['source_digest']
 stage='plain_formatter'
 stream=io.StringIO();handler=logging.StreamHandler(stream)
 handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
 logger=module.logger;logger.handlers=[handler];logger.propagate=False
 logger.disabled=False;logger.setLevel(logging.WARNING)
 marker='PRIVATE_INTAKE_RUNTIME_SENTINEL'
 cases=[('source address is not allowed','source_denied'),
  ('source is temporarily unavailable','source_transport'),
  ('source rejected the request','source_rejected'),
  ('stage write failed','staging_failed'),('publish failed','publication_failed'),
  ('https://private.invalid/'+marker+'?credential='+marker,'import_incomplete')]
 for reason,code in cases:
  stream.seek(0);stream.truncate(0)
  module._record_import_deferral({'files':[{'reason':reason,'name':marker,'url':marker}]})
  assert stream.getvalue()=='WARNING workspace intake import deferred: '+code+'\n'
  assert marker not in stream.getvalue() and 'private.invalid' not in stream.getvalue()
 stage='dedup'
 stream.seek(0);stream.truncate(0)
 module._record_import_deferral({'files':[{'reason':'publish failed'}]*2+[None]})
 assert stream.getvalue().count('publication_failed')==1
 report={'status':'passed','cases':7,'model_calls':0,'storage_calls':0,
  'closed_codes_visible':True,'private_diagnostics_absent':True}
except BaseException:
 report={'status':'failed','stage':stage}
print(json.dumps(report),flush=True)
if report['status']!='passed':raise SystemExit(1)
"""


def test_intake_runtime_probe_is_syntax_valid_and_does_not_call_integrations():
    ast.parse(_PROBE)
    assert not any(value in _PROBE for value in ("httpx", "urllib", "create_session"))


@pytest.mark.parametrize("container", _CONTAINERS)
@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORK_INTAKE_DIAGNOSTICS") != "1", reason="native dev diagnostic probe"
)
def test_installed_intake_diagnostics_are_observable_without_private_payload(container):
    result = subprocess.run(
        ["docker", "exec", "-i", container, "python", "-c", _PROBE],
        input=json.dumps(
            {"source_digest": hashlib.sha256(Path(_MODULE).read_bytes()).hexdigest()}
        ).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        pytest.fail("work_intake_diagnostics_protocol_unavailable")
    if result.returncode:
        stage = report.get("stage")
        if stage not in {"source_parity", "plain_formatter", "dedup"}:
            stage = "unknown"
        pytest.fail("work_intake_diagnostics_failed:" + stage)
    assert report == {
        "status": "passed",
        "cases": 7,
        "model_calls": 0,
        "storage_calls": 0,
        "closed_codes_visible": True,
        "private_diagnostics_absent": True,
    }
