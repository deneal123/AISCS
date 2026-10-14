"""Real pdfLaTeX errors retain identity across a vendor basename collision."""

import json
import os
import subprocess
import uuid

import pytest
from application.documents.builds import DocumentBuildManager

pytestmark = pytest.mark.skipif(
    os.environ.get("WORKSPACE_DOCUMENT_SOURCE_LIVE") != "1",
    reason="real disposable document compiler acceptance is opt-in",
)

_PROBE = r"""
import importlib.util,json,pathlib,subprocess,sys
sys.path.insert(0,'/opt/document-runtime')
s=importlib.util.spec_from_file_location('runner','/opt/document-runtime/runner.py')
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
project=pathlib.Path('/job')
identity=sys.argv[1]; source=project/identity
source.parent.mkdir(parents=True,exist_ok=True); source.write_text('x_y')
# An innocent managed source exists alongside the same-named vendor file.
managed=project/'content/body.tex'
if source!=managed:
 managed.parent.mkdir(parents=True,exist_ok=True); managed.write_text('Safe content')
(project/'main.tex').write_text(
 r'\documentclass{article}\begin{document}\input{'+identity+r'}\end{document}')
r=subprocess.run(['pdflatex','-no-shell-escape','-interaction=nonstopmode',
 '-halt-on-error','-file-line-error','main.tex'],cwd=project,
 stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
assert r.returncode!=0
log=(project/'main.log').read_text(errors='replace')
print(json.dumps({'diagnostics':m.diagnostics(log,compilation_failed=True)}))
"""


@pytest.mark.parametrize("relative", ["content/body.tex", "vendor/body.tex"])
def test_real_compiler_location_does_not_alias_vendor_source(relative):
    name = "gpthub-source-identity-" + uuid.uuid4().hex[:12]
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--memory=512m",
        "--cpus=1",
        "--pids-limit=64",
        "--tmpfs=/job:rw,noexec,nosuid,size=64m,mode=1777",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "--entrypoint=python3",
        "gpthub-document-runtime:latest",
        "-",
        relative,
    ]
    try:
        result = subprocess.run(command, input=_PROBE.encode(), capture_output=True, timeout=60)
        assert result.returncode == 0, "compiler_identity_probe_failed"
        report = json.loads(result.stdout)
        diagnostics = DocumentBuildManager._diagnostics(report, {"content/body.tex": "intro-001"})
        located = [item for item in diagnostics if item.code == "missing_math_delimiter"]
        assert len(located) == 1
        assert located[0].relative_path == "body.tex" and located[0].line == 1
        assert located[0].block_id == ("intro-001" if relative.startswith("content/") else "")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)
        remaining = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
            capture_output=True,
            timeout=30,
        )
        assert remaining.returncode == 0 and not remaining.stdout.strip(), "fixture_cleanup_failed"
