"""Opt-in safe receiver regression inside Linux, without compiler/model calls."""

import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = r"""
import io,json,os,tarfile,tempfile,sys
payload=json.load(sys.stdin)
namespace={'__name__':'private_receiver_probe'}
exec(payload['receiver'],namespace)
def archive(records):
 stream=io.BytesIO()
 with tarfile.open(fileobj=stream,mode='w',format=tarfile.USTAR_FORMAT) as tar:
  for name,data,kind in records:
   member=tarfile.TarInfo(name);member.type=kind;member.size=len(data)
   if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):member.linkname='../escape'
   tar.addfile(member,io.BytesIO(data))
 return stream.getvalue()
png=b'\x89PNG\r\n\x1a\n'+b'fixture-raster'
cases=[('ready',[('page-001.png',png,tarfile.REGTYPE),('page-002.png',png,tarfile.REGTYPE)]),
 ('traversal',[('../page-001.png',png,tarfile.REGTYPE)]),
 ('symlink',[('page-001.png',b'',tarfile.SYMTYPE)]),
 ('gap',[('page-002.png',png,tarfile.REGTYPE)]),
 ('duplicate',[('page-001.png',png,tarfile.REGTYPE)]*2),
 ('invalid_png',[('page-001.png',b'not-a-raster',tarfile.REGTYPE)]),('empty',[])]
passed=[]
for label,records in cases:
 with tempfile.TemporaryDirectory(prefix='document-raster-regression-') as root:
  output=root+'/output'
  bundle=archive(records)
  outer=archive([('document.pdf',b'%PDF-fixture',tarfile.REGTYPE),
   ('report.json',b'{}',tarfile.REGTYPE),('visual-pages.tar',bundle,tarfile.REGTYPE)])
  try:namespace['extract'](io.BytesIO(outer),output,1024,65536)
  except (ValueError,OSError,tarfile.TarError):
   assert label!='ready'
  else:
   assert label=='ready'
   assert open(output+'/visual-pages/page-1.png','rb').read()==png
   assert open(output+'/visual-pages/page-2.png','rb').read()==png
   assert open(output+'/visual-pages.tar','rb').read()==bundle
   assert sorted(os.listdir(output+'/visual-pages'))==['page-1.png','page-2.png']
  passed.append(label)
print(json.dumps({'cases':len(passed),'status':'passed'}))
"""


@pytest.mark.skipif(os.getenv("S37_LIVE_DOCUMENT_TRANSFER") != "1", reason="opt-in Linux receiver")
def test_visual_archive_expands_into_protected_page_paths():
    receiver = (
        Path(__file__).resolve().parents[1] / "service/infrastructure/document_output_runtime.py"
    )
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-c", _PROBE],
        input=json.dumps({"receiver": receiver.read_text("utf-8")}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, "visual_receiver_regression_failed"
    assert json.loads(result.stdout) == {"cases": 7, "status": "passed"}
