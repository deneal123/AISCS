"""Exact-source POSIX reader check in a fresh child, not a sidecar deployment."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

_PROBE = r"""
import hashlib, json, os, pathlib, subprocess, sys, tempfile
assert hashlib.sha256(SOURCE.encode()).hexdigest() == DIGEST
stage = 'fixture_setup'
try:
    with tempfile.TemporaryDirectory(prefix='gpthub-ide-read-fixture-') as directory:
        base = pathlib.Path(directory)
        root = base / 'repo'
        root.mkdir()
        (root / 'src').mkdir()
        (root / 'src' / 'main.py').write_text("print('hello')\n")
        (root / '.git').mkdir()
        (root / '.git' / 'config').write_text('PRIVATE')
        (root / '.gpthub-state').write_text('PRIVATE')
        (base / 'outside').write_text('PRIVATE')
        (root / 'dirlink').symlink_to(base, target_is_directory=True)
        (root / 'filelink').symlink_to(base / 'outside')
        (root / 'binary').write_bytes(b'\x00\xff')
        os.mkfifo(root / 'fifo')
        # A repo-controlled import hook must never execute in the reader.
        (root / 'sitecustomize.py').write_text("raise RuntimeError('REPO_IMPORT')")
        (root / 'json.py').write_text("raise RuntimeError('REPO_IMPORT')")

        def read(path='', operation='file'):
            result = subprocess.run([sys.executable, '-I', '-c', SOURCE],
                input=json.dumps({'root':str(root),'path':path,'operation':operation}).encode(),
                cwd=root, capture_output=True, timeout=3)
            assert result.returncode == 0
            return json.loads(result.stdout)

        stage = 'owned_relative_read'
        content = read('src/main.py')
        assert content['content'] == "print('hello')\n" and not content['truncated']
        assert content['digest'] == hashlib.sha256(content['content'].encode()).hexdigest()
        stage = 'path_and_special_file_boundaries'
        for path in ['../outside', '/etc/passwd', '.git/config', '.gpthub-state',
                     'dirlink/outside', 'filelink', 'src/../../outside']:
            assert read(path) == {'error':'ide_path_forbidden'}
        assert read('fifo') == {'error':'ide_file_unsupported'}
        assert read('absent') == {'error':'ide_file_missing'}
        assert read('binary')['kind'] == 'binary'
        stage = 'tree_filtering'
        tree = read('', 'tree')
        paths = {row['path'] for row in tree['entries']}
        assert paths == {'src','src/main.py','binary','sitecustomize.py','json.py'}
        assert not tree['truncated']
        assert all(not path.startswith('/') for path in paths)
        stage = 'bounded_unicode_prefix'
        (root / 'large').write_bytes(b'a' * (256*1024-1) + 'яtail'.encode())
        content = read('large')
        assert content['kind'] == 'text' and content['truncated'] and content['digest'] is None
        assert content['content'] == 'a' * (256*1024-1)
        stage = 'bounded_tree'
        nested = root
        for index in range(8):
            nested = nested / ('deep' + str(index))
            nested.mkdir()
        (nested / 'leaf').touch()
        for index in range(410):
            (root / ('file' + str(index))).touch()
        tree = read('', 'tree')
        assert tree['truncated'] and len(tree['entries']) == 400
        assert any(row.get('incomplete') for row in tree['entries'])
    assert not base.exists()
    print(json.dumps({'status':'passed','cleaned':True}))
except BaseException:
    print(json.dumps({'status':'failed','stage':stage}))
    raise SystemExit(1)
"""


def test_posix_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("IDE_LIVE_POSIX_READS") != "1", reason="explicit exact-source Linux reader acceptance"
)
def test_current_reader_posix_boundaries_in_fresh_process():
    source = (
        Path(__file__).resolve().parents[1] / "service/infrastructure/ide_read_runtime.py"
    ).read_text(encoding="utf-8")
    header = f"SOURCE={source!r}\nDIGEST={hashlib.sha256(source.encode()).hexdigest()!r}\n"
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
        input=(header + _PROBE).encode(),
        capture_output=True,
        timeout=40,
        check=False,
    )
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "ide_reader_report_missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, "ide_reader_failed_" + report.get("stage", "unknown")
    assert report == {"status": "passed", "cleaned": True}
