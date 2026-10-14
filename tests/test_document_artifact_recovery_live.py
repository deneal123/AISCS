"""Installed verifier with isolated files and real shell output, no compiler build."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_FILE = "service/application/documents/build_store.py"
_PROBE = """
import asyncio,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,'/opt/workspace-sidecar/service')
from application.documents import build_store
from domain.documents import DocumentArtifact,DocumentBuild
stage='source'
async def main():
 global stage
 expected=json.load(sys.stdin)
 assert hashlib.sha256(Path(build_store.__file__).read_bytes()).hexdigest()==expected['source']
 stage='fixture'
 with tempfile.TemporaryDirectory(prefix='artifact-recovery-') as directory:
  path=Path(directory)/'document.pdf'; path.write_bytes(b'isolated-artifact')
  build=DocumentBuild('probe','owned',directory,'generic_document',1,'rev','d'*64,'draft',False,
   state='preview_ready',artifacts=(DocumentArtifact('pdf','pdf','document.pdf','application/pdf',
    path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest(),str(path)),))
  async def actual(_item,command,**kwargs):
   result=subprocess.run(['sh','-c',command],capture_output=True,text=True,timeout=5)
   return SimpleNamespace(exit_code=result.returncode,stdout=result.stdout,
                          timed_out=False,truncated=False)
  store=build_store.BuildManifestStore(); registry=SimpleNamespace(exec_raw=actual)
  stage='valid'; assert await store.verify_artifacts(registry,None,build) is True
  valid=await actual(None,'echo __OK__')
  uncertain=(dict(timed_out=True),dict(truncated=True),dict(exit_code=None),
             dict(exit_code=False),dict(stdout='private-response'),dict(exit_code=124))
  for changes in uncertain:
   stage='uncertain'
   async def altered(*args,**kwargs): return SimpleNamespace(**{**vars(valid),**changes})
   try: await store.verify_artifacts(SimpleNamespace(exec_raw=altered),None,build)
   except RuntimeError as error: assert str(error)=='artifact verification unavailable'
   else: raise AssertionError
  stage='changed'; path.write_bytes(b'changed-artifact')
  assert await store.verify_artifacts(registry,None,build) is False
 return {'status':'passed','physical_checks':2,'uncertain_rejected':6,
         'source_matches':True,'temporary_files_cleaned':not Path(directory).exists()}
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','failure_code':'artifact_recovery_probe','stage':stage}));sys.exit(1)
"""


def test_artifact_recovery_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_ARTIFACT_RECOVERY") != "1", reason="installed isolated-file probe"
)
def test_installed_artifact_verification_requires_confirmed_result():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps({"source": hashlib.sha256((root / _FILE).read_bytes()).hexdigest()}),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    report = json.loads(result.stdout)
    assert result.returncode == 0, "artifact_recovery_probe_failed_" + report.get(
        "stage", "unknown"
    )
    assert report == {
        "status": "passed",
        "physical_checks": 2,
        "uncertain_rejected": 6,
        "source_matches": True,
        "temporary_files_cleaned": True,
    }
