import ast
import os

import pytest
from test_ide_write_live import run_probe

PROBE = r"""
import hashlib, pathlib, time
from infrastructure.ide_move_runtime import execute
root=pathlib.Path('/tmp/repo');root.mkdir();(root/'src').mkdir()
source=root/'main.py';source.write_bytes(b'print(1)\n');source.chmod(0o755)
request=dict(root=str(root),path='main.py',destination='src/main.py',expected_digest=hashlib.sha256(source.read_bytes()).hexdigest(),deadline=time.time()+10)
assert execute(request)==dict(moved=True,path='src/main.py',moved_from='main.py',size=9)
assert not source.exists() and (root/'src/main.py').read_bytes()==b'print(1)\n'
assert (root/'src/main.py').stat().st_mode & 0o777 == 0o755
source.write_bytes(b'KEEP')
request.update(expected_digest=None)
assert execute(request)=={'error':'ide_file_changed'}
assert source.read_bytes()==b'KEEP' and (root/'src/main.py').read_bytes()==b'print(1)\n'
request.update(destination='../outside')
assert execute(request)=={'error':'ide_path_forbidden'}
(root/'link').symlink_to('/tmp',target_is_directory=True)
request.update(destination='link/outside')
assert execute(request)=={'error':'ide_path_forbidden'}
request.update(destination='.git/config')
assert execute(request)=={'error':'ide_path_forbidden'}
request.update(destination='src/binary',expected_digest=None)
source.write_bytes(b'\x00\xff')
assert execute(request)['moved']
assert (root/'src/binary').read_bytes()==b'\x00\xff'
(root/'src/empty').mkdir()
request.update(path='src',destination='src/empty/nested',expected_digest=None)
assert execute(request)=={'error':'ide_path_forbidden'}
assert (root/'src/main.py').read_bytes()==b'print(1)\n'
(root/'bundle').mkdir()
request.update(destination='bundle/src')
assert execute(request)==dict(moved=True,path='bundle/src',moved_from='src',size=0)
assert not (root/'src').exists()
assert (root/'bundle/src/main.py').read_bytes()==b'print(1)\n'
assert (root/'bundle/src/binary').read_bytes()==b'\x00\xff'
assert (root/'bundle/src/empty').is_dir()
(root/'src').mkdir();(root/'src/keep').write_bytes(b'KEEP')
request.update(path='bundle/src',destination='src')
assert execute(request)=={'error':'ide_file_changed'}
assert (root/'src/keep').read_bytes()==b'KEEP'
assert (root/'bundle/src/binary').read_bytes()==b'\x00\xff'
print('{"status":"passed"}')
"""


def test_move_probe_parses():
    ast.parse(PROBE)


@pytest.mark.skipif(os.getenv("IDE_LIVE_WRITES") != "1", reason="explicit Docker acceptance")
def test_atomic_move_exact_source():
    run_probe(PROBE, ["ide_read_runtime", "ide_move_runtime"])
