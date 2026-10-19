"""Real Git objects/history in an isolated fixture; no external clone or user data."""

import ast
import os

import pytest
from test_ide_write_live import run_probe

_SOURCE = r"""
import pathlib, subprocess, time
import infrastructure.ide_git_runtime as kernel
source=pathlib.Path('/tmp/source');source.mkdir()
def command(*args):
    result=subprocess.run(['/usr/bin/git','-C',str(source),*args],capture_output=True,check=True)
    return result.stdout
command('init','--template=','--initial-branch=main')
(source/'main.py').write_text('print(1)\n')
command('add','main.py')
command('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','first')
(source/'main.py').write_text('print(2)\n')
command('add','main.py')
command('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','second')
sha=command('rev-parse','HEAD').decode().strip()
pack=command('pack-objects','--all','--stdout')
"""

PROBE = (
    _SOURCE
    + r"""
root=pathlib.Path('/tmp/target');root.mkdir()
request=dict(root=str(root),operation='clone',branch='main',origin='https://github.com/fixture/repo.git',commit=sha,deadline=time.time()+30)
assert kernel.setup(request,pack)==dict(initialized=True,branch='main')
assert (root/'main.py').read_bytes()==(source/'main.py').read_bytes()
assert subprocess.check_output(['/usr/bin/git','-C',str(root),'rev-list','--count','HEAD']).strip()==b'2'
assert subprocess.check_output(['/usr/bin/git','-C',str(root),'remote','get-url','origin']).strip()==b'https://github.com/fixture/repo.git'
assert not list(root.glob('.gpthub-*'))
assert kernel.status(str(root))==dict(initialized=True,branch='main')
try:
    kernel.setup(request,pack)
    raise AssertionError('overwritten')
except ValueError as error:
    assert str(error)=='ide_git_conflict'
# Fresh helper process has fresh globals; reset only the direct fixture kernel.
kernel._published=[];kernel._finished=False
empty=pathlib.Path('/tmp/empty');empty.mkdir();(empty/'keep.txt').write_text('KEEP')
request.update(root=str(empty),operation='init')
assert kernel.setup(request,b'')['initialized']
assert (empty/'keep.txt').read_text()=='KEEP'
assert not (empty/'.git/hooks').exists()
assert not list(empty.glob('.gpthub-*'))
print('{"status":"passed"}')
"""
)

STARTER_PROBE = (
    _SOURCE
    + r"""
def invoke(root, operation, *, replace=False, data=b'', branch='main'):
    kernel._published=[]; kernel._finished=False; kernel._stage=None
    request=dict(root=str(root),operation=operation,branch=branch,
        origin='https://github.com/fixture/repo.git',commit=sha,
        deadline=time.time()+30,replace_pristine_starter=replace)
    try:
        return kernel.setup(request,data)
    finally:
        kernel.cleanup()

def seed(name):
    root=pathlib.Path('/tmp')/name;root.mkdir()
    assert invoke(root,'init')==dict(initialized=True,branch='main')
    return root

def refused(root, *, data=pack, replace=True):
    try:
        invoke(root,'clone',replace=replace,data=data,branch='topic')
        raise AssertionError('changed seed was replaced')
    except (ValueError,OSError):
        pass
    assert not list(root.glob('.gpthub-*'))

root=seed('starter')
before=kernel.seed_digest(root/'.git')
refused(root,replace=False)
assert kernel.seed_digest(root/'.git')==before
assert invoke(root,'clone',replace=True,data=pack,branch='topic')==dict(initialized=True,branch='topic')
assert (root/'main.py').read_bytes()==(source/'main.py').read_bytes()
assert subprocess.check_output(['/usr/bin/git','-C',str(root),'rev-list','--count','HEAD']).strip()==b'2'
assert not list(root.glob('.gpthub-*'))
refused(root)

root=seed('changed-config')
kernel.git(str(root),'config','user.name','Keep fixture')
before=(root/'.git/config').read_bytes()
assert invoke(root,'init')==dict(initialized=True,branch='main')
assert (root/'.git/config').read_bytes()==before
refused(root)
assert (root/'.git/config').read_bytes()==before
assert not (root/'main.py').exists()

root=seed('user-files');(root/'keep.txt').write_bytes(b'KEEP')
refused(root)
assert (root/'keep.txt').read_bytes()==b'KEEP'

root=seed('bad-pack');before=kernel.seed_digest(root/'.git')
refused(root,data=b'PACKinvalid')
assert kernel.seed_digest(root/'.git')==before
assert set(p.name for p in root.iterdir())=={'.git'}

root=seed('exchange-failure');before=kernel.seed_digest(root/'.git')
original=kernel.exchange_seed
def unavailable(*args): raise OSError('fixture_exchange_unavailable')
kernel.exchange_seed=unavailable
refused(root)
kernel.exchange_seed=original
assert kernel.seed_digest(root/'.git')==before
assert set(p.name for p in root.iterdir())=={'.git'}

root=seed('late-config')
original_git=kernel.git
def change_during_checkout(directory,*args,**kwargs):
    original_git(directory,*args,**kwargs)
    if args[0]=='read-tree': (root/'.git/config').write_bytes(b'KEEP LATE CHANGE')
kernel.git=change_during_checkout
refused(root)
kernel.git=original_git
assert (root/'.git/config').read_bytes()==b'KEEP LATE CHANGE'
assert set(p.name for p in root.iterdir())=={'.git'}

root=seed('changed-head');kernel.git(str(root),'symbolic-ref','HEAD','refs/heads/custom')
refused(root)
assert (root/'.git/HEAD').read_text().strip()=='ref: refs/heads/custom'

root=seed('changed-mode');(root/'.git').chmod(0o700)
refused(root)
assert root.joinpath('.git').stat().st_mode & 0o777==0o700

root=seed('symlink-config');outside=pathlib.Path('/tmp/keep-outside');outside.write_bytes(b'KEEP')
root.joinpath('.git/config').unlink();root.joinpath('.git/config').symlink_to(outside)
refused(root)
assert outside.read_bytes()==b'KEEP' and root.joinpath('.git/config').is_symlink()
print('{"status":"passed"}')
"""
)


def test_git_probe_parses():
    ast.parse(PROBE)
    ast.parse(STARTER_PROBE)


@pytest.mark.skipif(os.getenv("IDE_LIVE_WRITES") != "1", reason="explicit Docker acceptance")
def test_git_setup_exact_source():
    run_probe(PROBE, ["ide_git_runtime"])


@pytest.mark.skipif(os.getenv("IDE_LIVE_WRITES") != "1", reason="explicit Docker acceptance")
def test_pristine_starter_clone_and_failed_publication_preserve_existing_data():
    run_probe(STARTER_PROBE, ["ide_git_runtime"])
