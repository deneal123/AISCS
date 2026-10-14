"""A real qpdf-valid standard-font PDF must not pass the embedding audit."""

import io
import json
import os
import subprocess
import tarfile
import uuid

import pytest
from domain.documents import audit_pdf, load_profile_catalog

pytestmark = pytest.mark.skipif(
    os.environ.get("WORKSPACE_DOCUMENT_FONTS_LIVE") != "1",
    reason="real isolated Poppler/qpdf acceptance is opt-in",
)


def unembedded_pdf() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    content = b"BT /F1 14 Tf 70 760 Td (Synthetic font audit fixture) Tj ET"
    objects.append(
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"
    )
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


@pytest.mark.parametrize("seam", ["compiler", "sidecar"])
def test_real_unembedded_font_is_rejected_by_both_audit_seams(seam: str) -> None:
    stream = io.BytesIO()
    pdf = unembedded_pdf()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        item = tarfile.TarInfo("fixture.pdf")
        item.size = len(pdf)
        archive.addfile(item, io.BytesIO(pdf))
    probe = (
        "import importlib.util,json,pathlib,sys; sys.path.insert(0,'/opt/document-runtime'); "
        "s=importlib.util.spec_from_file_location('runner','/opt/document-runtime/runner.py'); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "p=pathlib.Path('/job/fixture.pdf'); root=p.parent; "
        "info=m.output(['pdfinfo',str(p)],root,15); fonts=m.output(['pdffonts',str(p)],root,15); "
        "meta,diagnostics=m.pdf_metadata(p,root,15); "
        "q=m.run(['qpdf','--check',str(p)],root,15); "
        "print(json.dumps({'info':info,'fonts':fonts,'qpdf_ok':q.returncode==0,"
        "'codes':[d['code'] for d in diagnostics]}))"
    )
    name = "gpthub-font-probe-" + uuid.uuid4().hex[:12]
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
        "--entrypoint",
        "sh",
        "gpthub-document-runtime:latest",
        "-c",
        'cd /job && tar xf - && python3 -c "$1"',
        "probe",
        probe,
    ]
    try:
        result = subprocess.run(command, input=stream.getvalue(), capture_output=True, timeout=40)
        assert result.returncode == 0, "font_probe_unavailable"
        payload = json.loads(result.stdout)
        assert payload["qpdf_ok"], "synthetic_pdf_not_structurally_valid"
        profile = load_profile_catalog().get("generic_document")
        sidecar = audit_pdf(
            profile,
            pdfinfo_text=payload["info"],
            pdffonts_text=payload["fonts"],
            qpdf_ok=True,
            extracted_text="Synthetic font audit fixture",
        )
        if seam == "compiler":
            assert "font_not_embedded" in payload["codes"], "compiler_accepted_unembedded_font"
        else:
            assert any(item.code == "font_not_embedded" for item in sidecar), (
                "sidecar_accepted_unembedded_font"
            )
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
