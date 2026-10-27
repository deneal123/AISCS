"""Opt-in real compiler coverage; no provider calls, mounts or Library writes."""

import io
import os
import re
import subprocess
import tarfile
import uuid
from pathlib import Path

import pytest

from service.domain.documents.semantic.draft import DraftBlock
from service.domain.documents.semantic.rendering import _table

pytestmark = pytest.mark.skipif(
    os.environ.get("GPTHUB_DOCUMENT_TABLE_LIVE") != "1",
    reason="isolated Document Forge image acceptance is opt-in",
)


@pytest.mark.parametrize("columns", [5, 6])
def test_multipage_table_retains_every_row_inside_page_width(columns: int) -> None:
    style = (
        Path(__file__).resolve().parents[2]
        / "workspace/service/domain/documents/profile_data/_shared/gpthub-core.sty"
    ).read_bytes()
    block = DraftBlock(
        "coverage_table",
        "table",
        title="Coverage",
        columns=tuple(f"Col {index}" for index in range(columns)),
        rows=tuple(
            tuple(f"row{index:03d}" if column == 0 else "sample" for column in range(columns))
            for index in range(90)
        ),
    )
    source = (
        "\\documentclass[11pt,a4paper]{article}\n"
        "\\usepackage[margin=25mm]{geometry}\n"
        "\\usepackage{gpthub-core}\n\\begin{document}\n" + _table(block) + "\n\\end{document}\n"
    )
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, content in {"main.tex": source.encode(), "gpthub-core.sty": style}.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    name = "gpthub-table-probe-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--memory=768m",
        "--pids-limit=128",
        "--cpus=2",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/job:rw,size=64m,mode=1777",
        "--tmpfs",
        "/tmp:rw,size=128m,mode=1777",
        "--entrypoint",
        "sh",
        "gpthub-document-runtime:latest",
        "-c",
        "cd /job && tar xf - && "
        "xelatex -no-shell-escape -halt-on-error -interaction=nonstopmode main.tex "
        "> /tmp/compiler.log 2>&1 && "
        "xelatex -no-shell-escape -halt-on-error -interaction=nonstopmode main.tex "
        "> /tmp/compiler.log 2>&1 && "
        "cat /tmp/compiler.log && qpdf --check main.pdf && "
        "pdfinfo main.pdf && printf '\\nTABLE_TEXT_BEGIN\\n' && "
        "pdftotext -layout main.pdf -",
    ]
    try:
        result = subprocess.run(command, input=stream.getvalue(), capture_output=True, timeout=100)
        output = result.stdout.decode("utf-8", "replace")
        assert result.returncode == 0, "isolated_table_compile_failed"
        assert "Overfull" not in output, "table_exceeds_available_geometry"
        assert "Float too large" not in output, "table_is_unbreakable"
        pages = re.search(r"^Pages:\s+(\d+)", output, re.MULTILINE)
        assert pages and int(pages.group(1)) >= 2, "multipage_table_did_not_paginate"
        text = output.split("TABLE_TEXT_BEGIN\n", 1)[-1]
        for index in range(90):
            assert text.count(f"row{index:03d}") == 1, "table_row_missing_or_duplicated"
    finally:
        # Exact owned random name only; timeout/disconnect cannot leave the probe
        # running. Never sweep or stop other workspace/compiler containers.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
