"""Opt-in native HTTP rejection plus Docker event evidence of no allocation."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import hashlib,json,os,subprocess,time,urllib.request,urllib.error,uuid
from pathlib import Path
stage='source'
assert hashlib.sha256(Path('/opt/workspace-sidecar/service/domain/policy.py').read_text(encoding='utf-8').encode()).hexdigest()==DIGEST
base='http://localhost:8080'
headers={'Authorization':'Bearer '+os.environ['WORKSPACE_API_KEY'],'Content-Type':'application/json'}
def health():
 with urllib.request.urlopen(base+'/health',timeout=10) as r: return json.load(r)
try:
 before=health()['workspaces']; started=int(time.time()); stage='http'
 cases=[{'memory_bytes':0},{'pids_limit':-1},{'quota_bytes':0},{'cpus':True},
  {'cpus':float('inf')},{'exec_timeout_sec':float('nan')},{'root':'/'},
  {'root':'/workspace/../etc'},{'image':'--private-policy-marker'},
  {'read_only_root':'false'}]
 for policy in cases:
  owner='preflight-'+uuid.uuid4().hex
  req=urllib.request.Request(base+'/workspaces',headers=headers,
   data=json.dumps({'user_id':owner,'policy':policy}).encode(),method='POST')
  try:
   with urllib.request.urlopen(req,timeout=20) as r: result=json.load(r)
   # If a regression allocated a sandbox, clean up only that exact owned fixture.
   if 'workspace_id' in result and 'token' in result:
    wid=result['workspace_id']
    cleanup={'workspace_id':wid,'token':result['token'],'user_id':owner}
    with urllib.request.urlopen(urllib.request.Request(base+'/workspaces/'+wid,
     headers=headers,data=json.dumps(cleanup).encode(),method='DELETE'),timeout=20): pass
   raise AssertionError('invalid_policy_accepted')
  except urllib.error.HTTPError as error:
   status=error.code; raw=error.read(4097); error.close()
   assert status==422 and len(raw)<=4096
   payload=json.loads(raw); assert payload['error']=='invalid_request'
   assert 'private-policy-marker' not in raw.decode()
 stage='events'
 result=subprocess.run(['docker','events','--since',str(started),'--until',str(int(time.time())+1),
  '--filter','type=container','--filter','event=create','--filter','label=gpthub.workspace=1',
  '--format','{{json .}}'],capture_output=True,timeout=15)
 assert result.returncode==0 and not result.stdout.strip()
 assert health()['workspaces']==before
 print(json.dumps({'status':'passed','http_cases':len(cases),'create_events':0,'source_parity':True}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage})); raise SystemExit(1)
"""


def test_preflight_http_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_POLICY_PREFLIGHT") != "1", reason="native HTTP policy preflight"
)
def test_installed_http_rejects_invalid_policy_without_docker_allocation():
    source = (Path(__file__).parents[1] / "service/domain/policy.py").read_text(encoding="utf-8")
    header = f"DIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + _PROBE).encode(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    lines = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert lines, "policy_preflight_report_missing"
    report = json.loads(lines[-1])
    assert result.returncode == 0, "policy_preflight_failed_" + str(report.get("stage", "unknown"))
    assert report == {
        "status": "passed",
        "http_cases": 10,
        "create_events": 0,
        "source_parity": True,
    }
