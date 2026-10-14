"""Opt-in POSIX filesystem proof in dev; exact injected source, not boot parity."""

import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = """
import io,json,os,sys,tarfile,tempfile
from pathlib import Path
scope={'__name__':'output_probe'}
exec(json.load(sys.stdin)['source'],scope)
stage='valid'
def archive(members):
 stream=io.BytesIO()
 with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as value:
  for member,body in members: value.addfile(member,io.BytesIO(body) if body is not None else None)
 stream.seek(0);return stream
def regular(name,body=b'fixture'):
 info=tarfile.TarInfo(name);info.size=len(body);return info,body
try:
 checks=0
 with tempfile.TemporaryDirectory(prefix='document-output-probe-') as directory:
  root=Path(directory);outside=root/'private';outside.write_bytes(b'preserve')
  valid=root/'valid';valid.mkdir()
  scope['extract'](archive([regular('document.pdf'),regular('report.json',b'{}')]),str(valid),1024,4096)
  assert (valid/'document.pdf').read_bytes()==b'fixture';checks+=1
  bad=[]
  for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE,tarfile.DIRTYPE,
               tarfile.XHDTYPE,tarfile.GNUTYPE_LONGNAME):
   member=tarfile.TarInfo('document.pdf');member.type=kind;member.linkname=str(outside)
   bad.append([(member,None)])
  bad.extend([[regular('../private')],[regular('/private')],[regular('nested/file')],
              [regular('document.pdf'),regular('document.pdf')],
              [regular('document.pdf',b'x'*1025)]])
  for index,members in enumerate(bad):
   stage='member_rejected';target=root/f'rejected-{index}';target.mkdir()
   try: scope['extract'](archive(members),str(target),1024,4096)
   except (ValueError,OSError,tarfile.TarError): pass
   else: raise AssertionError
   assert outside.read_bytes()==b'preserve';checks+=1
  stage='target_symlink'
  destination=root/'symlink-target';destination.symlink_to(valid,target_is_directory=True)
  try: scope['extract'](archive([regular('document.pdf'),regular('report.json')]),str(destination),1024,4096)
  except OSError: pass
  else: raise AssertionError
  checks+=1
  stage='existing_symlink'
  target=root/'existing';target.mkdir();(target/'document.pdf').symlink_to(outside)
  try: scope['extract'](archive([regular('document.pdf'),regular('report.json')]),str(target),1024,4096)
  except FileExistsError: pass
  else: raise AssertionError
  assert outside.read_bytes()==b'preserve';checks+=1
  stage='truncated'
  target=root/'truncated';target.mkdir()
  try: scope['extract'](io.BytesIO(b'broken'),str(target),1024,4096)
  except ValueError: pass
  else: raise AssertionError
  checks+=1
 print(json.dumps({'status':'passed','checks':checks,'scratch_removed':not root.exists()}))
except BaseException:
 print(json.dumps({'status':'failed','stage':stage}));sys.exit(1)
"""


@pytest.mark.skipif(
    os.getenv("S37_LIVE_DOCUMENT_OUTPUT") != "1", reason="opt-in POSIX output probe"
)
def test_streamed_artifact_admission_on_posix():
    source = (
        Path(__file__).resolve().parents[1] / "service/infrastructure/document_output_runtime.py"
    ).read_text("utf-8")
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps({"source": source}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "posix_output_probe_failed"
    assert json.loads(result.stdout) == {"status": "passed", "checks": 15, "scratch_removed": True}
