"""Compile actual natbib/biblatex sources in a disposable offline runtime."""

import io
import json
import os
import subprocess
import tarfile
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("WORKSPACE_DOCUMENT_CITATIONS_LIVE") != "1", reason="isolated TeX opt-in"
)


@pytest.mark.parametrize("dialect", ["natbib", "biblatex"])
def test_real_citation_dialects_compile_and_pass_audit(dialect):
    setup, body, bibliography = (
        (
            r"\usepackage[numbers]{natbib}",
            r"See \citep{source}, \citet{source}, and \cite [p. 3] {source}.",
            r"\bibliographystyle{plainnat}\bibliography{bibliography/references}",
        )
        if dialect == "natbib"
        else (
            r"\usepackage[backend=biber]{biblatex}\addbibresource{bibliography/references.bib}",
            r"See \parencite[see][p. 3]{source}.",
            r"\printbibliography",
        )
    )
    source = (
        r"\documentclass[a4paper]{article}"
        + setup
        + r"\begin{document}"
        + body
        + bibliography
        + r"\end{document}"
    ).encode()
    files = {
        "main.tex": source,
        "bibliography/references.bib": b"@book{source,author={Example, Alex},title={Synthetic Source},year={2024},"
        b"publisher={Fixture Press}}",
        "document.toml": b'entrypoint="main.tex"\ndocumentclass="article"\npaper="a4"\n'
        b'orientation="portrait"\nbibliography_required=true\n'
        b'required_sections=[]\nsource_export="forbidden"\n',
    }
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        for name, value in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(value)
            archive.addfile(entry, io.BytesIO(value))
    probe = (
        "import sys,json,pathlib; sys.path.insert(0,'/opt/document-runtime'); "
        "import runner; root=pathlib.Path('/job'); "
        "result=runner.run(['latexmk','-pdf','-interaction=nonstopmode','-halt-on-error',"
        "'-file-line-error','-no-shell-escape','main.tex'],root,45); "
        "assert result.returncode==0,'compile_failed'; "
        "meta,diagnostics=runner.pdf_metadata(root/'main.pdf',root,15); "
        "diagnostics+=runner.diagnostics(runner.safe_log(root/'main.log')); "
        "diagnostics+=runner.manifest_audit(root,meta,publication=True); "
        "assert not any(d['severity']=='error' for d in diagnostics),'audit_failed'; "
        "print(json.dumps({'status':'passed','pages':meta['page_count']}))"
    )
    name = "gpthub-citation-probe-" + uuid4().hex[:12]
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
        "--memory=512m",
        "--pids-limit=64",
        "--cpus=1",
        "--tmpfs",
        "/job:rw,size=64m,mode=1777",
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
        result = subprocess.run(
            command, input=archive_bytes.getvalue(), capture_output=True, timeout=90, check=False
        )
        assert result.returncode == 0, "citation_runtime_probe_failed"
        outcome = json.loads(result.stdout)
        assert outcome["status"] == "passed" and outcome["pages"] > 0
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15, check=False)
