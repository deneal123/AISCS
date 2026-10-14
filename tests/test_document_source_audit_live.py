"""Actual isolated compiler audit must reject fake source coverage."""

import importlib.util
import io
import json
import os
import subprocess
import tarfile
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("WORKSPACE_DOCUMENT_SOURCE_LIVE") != "1",
    reason="real disposable document compiler acceptance is opt-in",
)


@pytest.mark.parametrize(
    "case",
    [
        "comment_heading",
        "orphan_heading",
        "comment_placeholder",
        "orphan_placeholder",
        "legal_requirement",
        "legal_requirement_preview",
        "legal_requirement_resolved",
    ],
)
def test_real_compiler_uses_only_active_document_sources(case: str) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "document_smoke", root / "scripts/smoke_document_runtime.py"
    )
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    payload, profile = smoke._source_archive("generic_document", publication=False)
    profile["required_sections"] = ["Mandatory"]
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        files = {item.name: archive.extractfile(item).read() for item in archive if item.isfile()}
    files["document.toml"] = smoke._project_manifest(profile, publication=False).encode()
    preamble = files["main.tex"].decode().split("\\begin{document}", 1)[0]
    body = "Synthetic corpus body."
    if case == "comment_heading":
        body = "% \\section{Mandatory}\n" + body
    elif case == "orphan_heading":
        files["unused.tex"] = b"\\section{Mandatory}"
    else:
        body = "\\section{Mandatory}\n" + body
        if case == "comment_placeholder":
            body += "\n% \\DocumentPlaceholder{old} {{OLD_FIELD}}\n"
        elif case == "orphan_placeholder":
            files["unused.tex"] = b"\\DocumentPlaceholder{old}"
    if case.startswith("legal_requirement"):
        import hashlib

        draft = {"version": 1, "blocks": [{"kind": "section", "title": "Mandatory"}]}
        files[".gpthub-authoring.json"] = json.dumps(
            {
                "schema_version": 1,
                "draft_version": 1,
                "profile_id": "generic_document",
                "draft": draft,
                "draft_digest": hashlib.sha256(
                    json.dumps(
                        draft, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
                "intent": {
                    "required_sections": ["Mandatory"],
                    "legal_fields": [
                        {
                            "name": "party",
                            "value": "Fixture party" if case.endswith("resolved") else None,
                            "required": True,
                        }
                    ],
                },
            }
        ).encode()
    files["main.tex"] = (preamble + "\\begin{document}\n" + body + "\n\\end{document}\n").encode()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, value in files.items():
            item = tarfile.TarInfo(name)
            item.size = len(value)
            archive.addfile(item, io.BytesIO(value))
    name = "gpthub-source-audit-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--memory=1536m",
        "--cpus=2",
        "--pids-limit=384",
        "--user=65534:65534",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--tmpfs",
        "/job:rw,size=64m,mode=1777",
        "--tmpfs",
        "/output:rw,size=128m,mode=1777",
        "--tmpfs",
        "/tmp:rw,size=256m,mode=1777",
        "--entrypoint",
        "sh",
        "gpthub-document-runtime:latest",
        "-c",
        "cd /job && tar xf - && python3 /opt/document-runtime/runner.py "
        "--project /job --entrypoint main.tex --engine xelatex --timeout 90 "
        + ("--publication " if case in {"legal_requirement", "legal_requirement_resolved"} else "")
        + "> /tmp/runner.log 2>&1; cat /output/report.json",
    ]
    try:
        result = subprocess.run(command, input=stream.getvalue(), capture_output=True, timeout=130)
        report = json.loads(result.stdout)
        codes = {item.get("code") for item in report.get("diagnostics", [])}
        if case == "legal_requirement":
            assert report["status"] == "failed", "critical_requirement_omitted_and_final_accepted"
            assert "unresolved_placeholder" in codes, "semantic_requirement_not_audited"
        elif case == "legal_requirement_preview":
            assert report["status"] == "ready", "unresolved_preview_was_blocked"
            assert any(
                item["code"] == "unresolved_placeholder" and item["severity"] == "warning"
                for item in report["diagnostics"]
            )
        elif case == "legal_requirement_resolved":
            assert report["status"] == "ready", "resolved_requirement_was_blocked"
            assert "unresolved_placeholder" not in codes
        elif case.endswith("heading"):
            assert report["status"] == "failed", "fake_heading_accepted"
            assert "required_section" in codes, "missing_heading_not_reported"
        else:
            assert report["status"] == "ready", "inactive_placeholder_blocked_document"
            assert "unresolved_placeholder" not in codes, "inactive_placeholder_was_audited"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
