"""Installed manifest I/O with isolated files, no user workspace or compiler."""

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
from domain.documents import DocumentBuild
stage='source'
async def main():
 global stage
 expected=json.load(sys.stdin)
 assert hashlib.sha256(Path(build_store.__file__).read_bytes()).hexdigest()==expected['source']
 stage='filesystem'
 with tempfile.TemporaryDirectory(prefix='manifest-ack-') as directory:
  item=SimpleNamespace(workspace_id='owned',policy=SimpleNamespace(root=directory))
  build=DocumentBuild('probe','owned',directory+'/paper','generic_document',1,'rev','d'*64,'draft',False)
  outputs={}
  async def actual(_item,command,**kwargs):
   result=subprocess.run(['sh','-c',command],input=kwargs.get('stdin_payload'),
                         capture_output=True,timeout=5)
   return SimpleNamespace(exit_code=result.returncode,stdout=result.stdout.decode('utf-8'),
                          timed_out=False,truncated=False)
  store=build_store.BuildManifestStore(); registry=SimpleNamespace(exec_raw=actual)
  assert await store.load(registry,item)==()
  async def captured(_item,command,**kwargs):
   result=await actual(_item,command,**kwargs); outputs['last']=result; return result
  registry.exec_raw=captured
  await store.save(registry,item,build); save=outputs['last']
  records=await store.load(registry,item); load=outputs['last']
  assert len(records)==1 and records[0].manifest_dict()==build.manifest_dict()
  await store.delete(registry,item,build.build_id); delete=outputs['last']
  assert await store.load(registry,item)==()
  stage='uncertain'
  rejected=0
  for operation,result in (('save',save),('load',load),('delete',delete)):
   for changes in (dict(exit_code=None),dict(exit_code=False),dict(exit_code='0'),
                   dict(timed_out=True),dict(truncated=True),dict(stdout=''),
                   dict(stdout='PRIVATE-PROBE '+result.stdout)):
    async def altered(*args,**kwargs): return SimpleNamespace(**{**vars(result),**changes})
    registry.exec_raw=altered
    try:
     if operation=='save': await store.save(registry,item,build)
     elif operation=='load': await store.load(registry,item)
     else: await store.delete(registry,item,build.build_id)
    except RuntimeError: rejected+=1
    else: raise AssertionError
 return {'status':'passed','physical_checks':5,'uncertain_rejected':rejected,
         'source_matches':True,'temporary_files_cleaned':not Path(directory).exists()}
try: print(json.dumps(asyncio.run(main())))
except BaseException:
 print(json.dumps({'status':'failed','failure_code':'manifest_ack_probe','stage':stage}));sys.exit(1)
"""


def test_manifest_ack_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_MANIFEST_ACK") != "1", reason="installed isolated-file probe"
)
def test_installed_manifest_io_requires_complete_acknowledgement():
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
    assert result.returncode == 0, "manifest_ack_probe_failed_" + report.get("stage", "unknown")
    assert report == {
        "status": "passed",
        "physical_checks": 5,
        "uncertain_rejected": 21,
        "source_matches": True,
        "temporary_files_cleaned": True,
    }
