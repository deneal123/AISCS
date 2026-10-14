"""Real Poppler must report and reject a mismatched non-first PDF page."""

import io
import json
import os
import subprocess
import tarfile
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("WORKSPACE_DOCUMENT_GEOMETRY_LIVE") != "1",
    reason="real isolated per-page geometry acceptance is opt-in",
)


def mixed_pdf(*, rotated: bool, all_landscape: bool = False) -> bytes:
    second = b"/MediaBox [0 0 595.28 841.89] /Rotate 90" if rotated else b"/MediaBox [0 0 612 792]"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] "
        b"/Resources << >> /Contents 5 0 R >>",
        b"<< /Type /Page /Parent 2 0 R " + second + b" /Resources << >> /Contents 5 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    if all_landscape:
        for index in (2, 3):
            objects[index] = (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 841.89 595.28] "
                b"/Resources << >> /Contents 5 0 R >>"
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


@pytest.mark.parametrize("case", ["wrong_size", "rotated", "allowed_landscape"])
def test_real_pages_must_match_profile(case: str) -> None:
    landscape = case == "allowed_landscape"
    files = {
        "fixture.pdf": mixed_pdf(rotated=case == "rotated", all_landscape=landscape),
        "main.tex": rb"\documentclass{article}\begin{document}Synthetic\end{document}",
        "document.toml": (
            b'entrypoint="main.tex"\ndocumentclass="article"\npaper="a4"\n'
            b'orientation="portrait"\nanonymize=false\nbibliography_required=false\n'
        ),
    }
    if landscape:
        files["document.toml"] = files["document.toml"].replace(b'"portrait"', b'"landscape"')
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, value in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(value)
            archive.addfile(item, io.BytesIO(value))
    probe = (
        "import importlib.util,json,pathlib,sys; sys.path.insert(0,'/opt/document-runtime'); "
        "s=importlib.util.spec_from_file_location('runner','/opt/document-runtime/runner.py'); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "root=pathlib.Path('/job'); p=root/'fixture.pdf'; "
        "meta,diagnostics=m.pdf_metadata(p,root,15); "
        "diagnostics+=m.manifest_audit(root,meta,publication=False); "
        "q=m.run(['qpdf','--check',str(p)],root,15); "
        "print(json.dumps({'qpdf_ok':q.returncode==0,'codes':[d['code'] for d in diagnostics]}))"
    )
    name = "gpthub-page-probe-" + uuid.uuid4().hex[:12]
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
        assert result.returncode == 0, "page_probe_unavailable"
        payload = json.loads(result.stdout)
        assert payload["qpdf_ok"], "synthetic_pdf_not_structurally_valid"
        if landscape:
            assert payload["codes"] == [], "allowed_landscape_rejected"
        else:
            code = "page_orientation" if case == "rotated" else "page_geometry"
            assert code in payload["codes"], "non_first_page_bypassed_profile"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
