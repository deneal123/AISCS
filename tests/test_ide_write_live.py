"""Exact-source POSIX mutation acceptance in a disposable, networkless container."""

import ast
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

PROBE = r"""
import hashlib, pathlib, time
from infrastructure.ide_write_runtime import execute
from infrastructure.ide_read_runtime import read_file
root = pathlib.Path('/tmp/repo')
root.mkdir()
def write(path, content=b'', digest=None, operation='file'):
    return execute(dict(root=str(root),path=path,operation=operation,
        expected_digest=digest,deadline=time.time()+10),content)
assert write('src',operation='directory')['kind']=='dir'
assert write('src/main.py',b'print(1)\n')['written']
path=root/'src/main.py'
digest=hashlib.sha256(path.read_bytes()).hexdigest()
assert write('src/main.py')['error']=='ide_file_changed'
assert write('src/main.py',b'changed','a'*64)['error']=='ide_file_changed'
path.chmod(0o755)
assert write('src/main.py',b'print(2)\n',digest)['written']
assert path.stat().st_mode & 0o777 == 0o755
assert path.read_bytes()==b'print(2)\n'
(root/'link').symlink_to('/tmp',target_is_directory=True)
assert write('link/escape')['error']=='ide_path_forbidden'
for name in ['../escape','.git/config','/tmp/escape','src/../../escape']:
    assert write(name)['error']=='ide_path_forbidden'
assert write('nul',b'\0')['error']=='ide_file_unsupported'
assert write('large',b'x'*(262144+1))['error']=='ide_write_limit'
blob=b'PK\x03\x04\0\xff'+b'x'*300000
assert write('opaque.zip',blob,operation='import')['digest']==hashlib.sha256(blob).hexdigest()
assert (root/'opaque.zip').read_bytes()==blob
assert (root/'opaque.zip').stat().st_mode & 0o777 == 0o644
assert write('opaque.zip',b'replace',operation='import')['error']=='ide_file_changed'
assert write('new.bin',blob,'a'*64,operation='import')['error']=='invalid_request'
assert write('link/escape',blob,operation='import')['error']=='ide_path_forbidden'
assert write('large.bin',b'x'*(20*1024*1024+1),operation='import')['error']=='ide_write_limit'
assert write('empty.bin',b'',operation='import')['written']
assert sorted(p.name for p in root.iterdir())==['empty.bin','link','opaque.zip','src']
assert not (root/'.git').exists()
assert not list(root.rglob('.gpthub-write-*'))
print('{"status":"passed"}')
"""


def test_probe_parses():
    ast.parse(PROBE)


@pytest.mark.skipif(os.getenv("IDE_LIVE_WRITES") != "1", reason="explicit Docker acceptance")
def test_exact_source_atomic_writes():
    run_probe(PROBE, ["ide_read_runtime", "ide_write_runtime"])


def run_probe(probe, extra):
    modules = [
        "ide_bundle_format",
        "ide_bundle_files",
        "ide_restore_receipt",
        "ide_bundle_runtime",
        *extra,
    ]
    folder = Path(__file__).resolve().parents[1] / "service/infrastructure"
    sources = {
        "infrastructure." + name: (folder / (name + ".py")).read_text(encoding="utf8")
        for name in modules
    }
    bootstrap = "import sys,types\np=types.ModuleType('infrastructure');p.__path__=[]\nsys.modules['infrastructure']=p\n"
    bootstrap += f"sources={sources!r}\n"
    bootstrap += "for name,source in sources.items():\n m=types.ModuleType(name);sys.modules[name]=m;exec(compile(source,name,'exec'),m.__dict__)\n"
    name = "gpthub-ide-write-fixture-" + uuid4().hex
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network=none",
                "--read-only",
                "--user=65534:65534",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=256m",
                "--pids-limit=64",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=67108864,mode=1777",
                "-i",
                "gpthub-workspace-runtime:latest",
                "python3",
                "-I",
                "-",
            ],
            input=(bootstrap + probe).encode(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()[-2000:]
        assert json.loads(result.stdout) == {"status": "passed"}
    finally:
        # Exact UUID fixture only; never a registry/user runtime.
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False)
