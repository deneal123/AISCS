"""Opt-in installed real compiler/Workspace transfer; no model or Library billing."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import asyncio,hashlib,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,'/opt/workspace-sidecar/service')
from types import SimpleNamespace
from application.documents.projects import scaffold_archive
from application.documents import artifact_integrity
from domain.documents import load_profile_catalog
from domain.policy import WorkspacePolicy
from infrastructure import document_compiler as module
from infrastructure.document_cleanup import container_absent
from infrastructure.document_compiler import DockerDocumentCompiler,_command
from infrastructure import document_output_runtime
from infrastructure import document_report
stage='source_parity'
expected=json.load(sys.stdin)
async def main():
 global stage
 for imported in (module,document_output_runtime,document_report,artifact_integrity):
  assert hashlib.sha256(Path(imported.__file__).read_bytes()).hexdigest()==expected[imported.__name__]
 stage='report_admission'
 for payload in (b'[]',b'{"status":"ready","value":NaN}',
                 b'{"status":"failed","failure_code":"private-report-body"}',
                 b'{"status":"ready"}'+b' '*262144+b'private-report-body'):
  assert module.parse_report(payload,0) is None
 valid={'status':'ready','diagnostics':[],'page_count':1,'page_width_pt':595,'page_height_pt':842,
  'artifact':{'filename':'document.pdf','size':100,'sha256':'a'*64}}
 assert module.ready_artifacts_valid(valid,final=False,artifact_limit=100,visual_limit=256)
 for changes in ({'artifact':None},{'page_count':True},{'page_width_pt':'595'},
                 {'diagnostics':[{'severity':'error','code':'pdf_invalid'}]},
                 {'artifact':{'filename':'document.pdf','size':True,'sha256':'a'*64}}):
  assert not module.ready_artifacts_valid(valid|changes,final=False,artifact_limit=100,visual_limit=256)
 assert not module.ready_artifacts_valid(valid,final=True,artifact_limit=100,visual_limit=256)
 compiler=DockerDocumentCompiler();prepared=None;source=None
 marker=uuid.uuid4().hex
 try:
  stage='source_container'
  code,raw=await _command('docker','create','--label',f'gpthub.document.transfer_probe={marker}',
   '--network','none','--read-only','--user','65534:65534','--cap-drop','ALL',
   '--security-opt','no-new-privileges','--memory','128m','--cpus','0.5','--pids-limit','64',
   '--tmpfs','/workspace:rw,size=32m,mode=1777','--tmpfs','/tmp:rw,size=16m,mode=1777',
   '--entrypoint','sleep',WorkspacePolicy().image,'300')
  assert code==0;source=raw.decode().strip()
  assert len(source)==64 and all(c in '0123456789abcdef' for c in source)
  code,_=await _command('docker','start',source);assert code==0
  stage='scaffold'
  profile=load_profile_catalog().get('generic_document');assert profile is not None
  code,_=await _command('docker','exec',source,'mkdir','-p','/workspace/documents/paper');assert code==0
  archive=scaffold_archive(profile,mode='draft',locale='ru-RU')
  code,_=await _command('docker','exec','-i',source,'tar','-C','/workspace/documents/paper',
   '-xf','-',input_bytes=archive);assert code==0
  stage='compile'
  reference=SimpleNamespace(container_id=source)
  prepared=await compiler.prepare(reference,workspace_root='/workspace',project_path='/workspace/documents/paper')
  result=await compiler.execute(prepared,entrypoint='main.tex',engine=profile.engine,final=False)
  assert result.status=='ready' and result.report['artifact']['size']>0
  stage='final_inventory'
  result=await compiler.execute(prepared,entrypoint='main.tex',engine=profile.engine,final=True)
  assert result.status=='ready'
  assert result.report['visual_bundle']['page_count']==result.report['page_count']
  stage='publication'
  target='/workspace/.gpthub-document/transfer-'+marker
  await compiler.publish_outputs(prepared,reference,staging_dir=target)
  await artifact_integrity.verify_staged_artifacts(compiler,reference,target,result.report)
  digest,size=await compiler.artifact_facts(reference,target+'/document.pdf')
  assert digest==result.report['artifact']['sha256'] and size==result.report['artifact']['size']
  code,raw=await _command('docker','exec',source,'python3','-c',
   "import os,sys; print(','.join(sorted(os.listdir(sys.argv[1]))))",target)
  assert code==0
  names=set(raw.decode().strip().split(','))
  assert {'document.pdf','report.json'}.issubset(names)
  assert names.issubset(document_output_runtime.ARTIFACT_NAMES|{'visual-pages'})
  stage='protected_page_inventory'
  for page in range(1,result.report['page_count']+1):
   digest,size=await compiler.artifact_facts(reference,target+f'/visual-pages/page-{page}.png',
    max_bytes=16*1024*1024)
   assert size>8 and len(digest)==64
  stage='physical_mismatch_refusal'
  code,_=await _command('docker','exec',source,'python3','-c',
   "from pathlib import Path;import sys;p=Path(sys.argv[1]);v=p.read_bytes();p.write_bytes(bytes([v[0]^1])+v[1:])",
   target+'/document.pdf')
  assert code==0
  try: await artifact_integrity.verify_staged_artifacts(compiler,reference,target,result.report)
  except module.CompilerFailure as failure: assert failure.code=='artifact_invalid'
  else: raise AssertionError
  stage='symlink_refusal'
  code,_=await _command('docker','exec',prepared.container_id,'python3','-c',
   "from pathlib import Path;p=Path('/output/document.pdf');p.unlink();p.symlink_to('/job/paper/main.tex')")
  assert code==0
  try: await compiler.publish_outputs(prepared,reference,staging_dir=target+'-refused')
  except module.CompilerFailure as failure: assert failure.code=='runtime_unavailable'
  else: raise AssertionError
  code,_=await _command('docker','exec',source,'test','!','-e',target+'-refused/document.pdf')
  assert code==0
  return {'loaded_source_matches':True,'report_refused':True,'metadata_refused':True,
   'final_inventory_admitted':True,'physical_mismatch_refused':True,
   'deterministic_build':True,'stream_digest_matches':True,
   'roles_only':True,'symlink_refused':True,'protected_page_inventory':True}
 finally:
  try:
   if prepared is not None:
    assert await compiler.destroy(prepared.container_id)
  finally:
   if source is not None:
    code,label=await _command('docker','inspect','--format',
     '{{index .Config.Labels "gpthub.document.transfer_probe"}}',source)
    assert code==0 and label.decode().strip()==marker
    await _command('docker','rm','-f',source)
    assert await container_absent(_command,source)
try:
 print(json.dumps({'status':'passed','checks':asyncio.run(main()),'fixtures_removed':True}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_TRANSFER") != "1", reason="opt-in compiler transfer"
)
def test_installed_compiler_output_transfer_and_symlink_refusal():
    root = Path(__file__).resolve().parents[1] / "service/infrastructure"
    expected = {
        f"infrastructure.{name}": hashlib.sha256((root / f"{name}.py").read_bytes()).hexdigest()
        for name in ("document_compiler", "document_output_runtime", "document_report")
    }
    expected["application.documents.artifact_integrity"] = hashlib.sha256(
        (root.parent / "application/documents/artifact_integrity.py").read_bytes()
    ).hexdigest()
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps(expected),
        text=True,
        capture_output=True,
        timeout=360,
        check=False,
    )
    assert result.returncode == 0, "installed_transfer_probe_failed"
    assert json.loads(result.stdout) == {
        "status": "passed",
        "fixtures_removed": True,
        "checks": {
            "loaded_source_matches": True,
            "report_refused": True,
            "metadata_refused": True,
            "final_inventory_admitted": True,
            "physical_mismatch_refused": True,
            "deterministic_build": True,
            "stream_digest_matches": True,
            "roles_only": True,
            "symlink_refused": True,
            "protected_page_inventory": True,
        },
    }
