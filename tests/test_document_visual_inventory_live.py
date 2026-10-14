"""Real PDF inventory and Poppler rasterization in a disposable local container."""

import io
import json
import os
import subprocess
import tarfile
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("WORKSPACE_DOCUMENT_VISUAL_LIVE") != "1",
    reason="real isolated visual inventory acceptance is opt-in",
)


def blank_pdf(pages: int) -> bytes:
    children = " ".join(f"{index} 0 R" for index in range(3, pages + 3))
    stream_id = pages + 3
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{children}] /Count {pages} >>".encode(),
        *[
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] "
            f"/Resources << >> /Contents {stream_id} 0 R >>".encode()
            for _ in range(pages)
        ],
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(pdf)


@pytest.mark.parametrize("case", ["over_limit", "complete", "partial"])
def test_actual_visual_page_inventory(case: str) -> None:
    pages = 201 if case == "over_limit" else 3
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        pdf = blank_pdf(pages)
        item = tarfile.TarInfo("fixture.pdf")
        item.size = len(pdf)
        archive.addfile(item, io.BytesIO(pdf))
    probe = r"""
import importlib.util,json,pathlib,sys,tarfile
from types import SimpleNamespace
sys.path.insert(0,'/opt/document-runtime')
s=importlib.util.spec_from_file_location('runner','/opt/document-runtime/runner.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
root=pathlib.Path('/job'); out=pathlib.Path('/output'); pdf=root/'fixture.pdf'
original=m.run; raster_started=False; names=[]; png=False; accepted=False
case=sys.argv[1]
def invoke(args,*rest):
 global raster_started
 if args[0]=='pdftoppm':
  raster_started=True
  if case=='over_limit': return SimpleNamespace(returncode=1,stdout=b'')
 result=original(args,*rest)
 if args[0]=='pdftoppm' and case=='partial':
  files=sorted((out/'visual-pages').glob('page-*.png'))
  if files: files[-1].unlink()
 return result
q=original(['qpdf','--check',str(pdf)],root,15)
m.run=invoke
try:
 bundle,preview=m.visual_bundle(pdf,out,root,30)
 with tarfile.open(bundle) as archive:
  names=archive.getnames()
  png=all(archive.extractfile(member).read(8)==b'\x89PNG\r\n\x1a\n' for member in archive)
 accepted=True
except ValueError: pass
print(json.dumps({'qpdf_ok':q.returncode==0,'raster_started':raster_started,
 'accepted':accepted,'names':names,'png':png}))
"""
    name = "gpthub-visual-probe-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--user=65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=256m",
        "--pids-limit=64",
        "--cpus=1",
        "--tmpfs",
        "/job:rw,size=16m,mode=1777",
        "--tmpfs",
        "/tmp:rw,size=128m,mode=1777",
        "--tmpfs",
        "/output:rw,size=32m,mode=1777",
        "--entrypoint",
        "sh",
        "gpthub-document-runtime:latest",
        "-c",
        'cd /job && tar xf - && python3 -c "$1" "$2"',
        "probe",
        probe,
        case,
    ]
    try:
        result = subprocess.run(command, input=stream.getvalue(), capture_output=True, timeout=60)
        assert result.returncode == 0, "visual_probe_unavailable"
        payload = json.loads(result.stdout)
        assert payload["qpdf_ok"], "synthetic_pdf_not_structurally_valid"
        if case == "over_limit":
            assert not payload["raster_started"], "over_limit_pdf_started_raster"
            assert not payload["accepted"]
        elif case == "partial":
            assert payload["raster_started"] and not payload["accepted"], "missing_page_accepted"
        else:
            assert payload["accepted"] and payload["png"]
            assert payload["names"] == ["page-001.png", "page-002.png", "page-003.png"]
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
