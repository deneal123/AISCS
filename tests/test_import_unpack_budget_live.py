"""Opt-in extraction checks on the isolated offline workspace runtime image."""

import base64
import io
import os
import zipfile
from uuid import uuid4

import pytest
from application import importer
from test_import_staging_atomicity_live import docker

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(os.getenv("S37_LIVE_IMPORT_ATOMICITY") != "1", reason="native import shell"),
]


@pytest.mark.parametrize(
    "scenario",
    [
        "oversize",
        "exact",
        "existing_edit",
        "destination_symlink",
        "dangling_member",
        "directory_swap",
    ],
)
async def test_native_unpack_budget_and_edit_preservation(scenario, monkeypatch):
    name = "s37-unpack-" + uuid4().hex
    monkeypatch.setattr(importer, "MAX_UNPACKED_BYTES", 10)
    entries = [("a", b"x" * 6), ("b", b"y" * (5 if scenario == "oversize" else 4))]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in entries:
            archive.writestr(path, data)
    try:
        await docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "gpthub.s37.unpack=1",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--memory=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--tmpfs",
            "/workspace:rw,size=32m,mode=1777",
            "--tmpfs",
            "/escape:rw,size=1m,mode=1777",
            "gpthub-workspace-runtime:latest",
            "sleep",
            "180",
        )
        await docker(
            "exec",
            "-i",
            name,
            "sh",
            "-c",
            "base64 -d > /workspace/source.zip",
            payload=base64.b64encode(stream.getvalue()),
        )
        if scenario == "existing_edit":
            await docker(
                "exec",
                name,
                "sh",
                "-c",
                "mkdir /workspace/source && printf edit > /workspace/source/a",
            )
        if scenario == "destination_symlink":
            await docker("exec", name, "ln", "-s", "/escape", "/workspace/source")
        if scenario == "dangling_member":
            await docker(
                "exec",
                name,
                "sh",
                "-c",
                "mkdir /workspace/source && ln -s untouched /workspace/source/a",
            )
        if scenario == "directory_swap":
            import shlex

            args = shlex.split(importer.unpack_command("/workspace", "source.zip"))
            start = args.index("python3")
            script = args[start + 2]
            wrapper = """import os,tempfile,sys
original_open=os.open
original_temp=tempfile.mkstemp
swapped=False
def swap():
    global swapped
    if not swapped:
        swapped=True
        os.rename('/workspace/source','/workspace/retained')
        os.symlink('/escape','/workspace/source')
def open_hook(path,*args,**kwargs):
    if isinstance(path,str) and path.startswith('.unpack-'):
        swap()
    return original_open(path,*args,**kwargs)
def temp_hook(*args,**kwargs):
    swap()
    return original_temp(*args,**kwargs)
os.open=open_hook
tempfile.mkstemp=temp_hook
"""
            report = await docker(
                "exec", name, "python3", "-c", wrapper + script, *args[start + 3 :]
            )
            assert "__OK__ 2" in report, "race fixture must exercise successful descriptor writes"
        else:
            report = await docker(
                "exec", name, "sh", "-c", importer.unpack_command("/workspace", "source.zip")
            )
        check = """from pathlib import Path
p=Path('/workspace/source')
assert not list(p.rglob('.unpack-*'))
"""
        if scenario == "directory_swap":
            check += "assert not list(Path('/escape').iterdir())\n"
            check += "assert p.is_symlink()\n"
            check += "assert Path('/workspace/retained/a').read_bytes()==b'x'*6\n"
            check += "assert Path('/workspace/retained/b').read_bytes()==b'y'*4\n"
            check += "assert not list(Path('/workspace/retained').rglob('.unpack-*'))\n"
        elif scenario == "destination_symlink":
            assert "__REFUSED__" in report and "__OK__" not in report
            check += "assert not list(Path('/escape').iterdir())\nassert p.is_symlink()\n"
        elif scenario == "dangling_member":
            assert "__OK__" in report
            check += "assert (p/'a').is_symlink()\nassert not (p/'untouched').exists()\n"
            check += "assert (p/'b').read_bytes()==b'y'*4\n"
        elif scenario == "oversize":
            assert "__TRUNCATED__" in report and "__OK__" not in report
            check += "assert (p/'a').read_bytes()==b'x'*6\nassert not (p/'b').exists()\n"
        else:
            assert "__OK__" in report and "__TRUNCATED__" not in report
            expected = "b'edit'" if scenario == "existing_edit" else "b'x'*6"
            check += (
                f"assert (p/'a').read_bytes()=={expected}\nassert (p/'b').read_bytes()==b'y'*4\n"
            )
        await docker("exec", name, "python3", "-c", check)
    finally:
        # Exact isolated fixture only; never remove managed user workspaces.
        await docker("rm", "-f", name)
