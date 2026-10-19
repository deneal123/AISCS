"""Opt-in exact-source, unprivileged Linux capsule roundtrip; not deployment."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

_PROBE = r"""
import hashlib, io, json, os, sys, types, unittest
stage = 'source_parity'
try:
    assert os.getuid() == 65534, 'probe_must_be_unprivileged'
    package = types.ModuleType('infrastructure')
    package.__path__ = []
    sys.modules['infrastructure'] = package
    for name, (source, digest) in SOURCES.items():
        assert hashlib.sha256(source.encode()).hexdigest() == digest
        module = types.ModuleType(name)
        module.__file__ = '/exact-source-probe/' + name.replace('.', '/') + '.py'
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    stage = 'capsule_posix_suite'
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules['capsule_fixture_tests'])
    assert suite.countTestCases() == 20
    result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    failures = [test.id().split('.')[-1] for test, _ in result.failures + result.errors]
    report = dict(status='passed' if result.wasSuccessful() and not result.skipped else 'failed',
                  tests=result.testsRun, skipped=len(result.skipped), failures=failures)
    print(json.dumps(report))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
except SystemExit:
    raise
except BaseException:
    print(json.dumps(dict(status='failed', stage=stage)))
    raise SystemExit(1)
"""


def test_capsule_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("IDE_LIVE_BUNDLES") != "1", reason="explicit unprivileged Linux capsule acceptance"
)
def test_current_capsule_capture_restore_as_unprivileged_linux_user():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "infrastructure.ide_bundle_format": root / "service/infrastructure/ide_bundle_format.py",
        "infrastructure.ide_bundle_files": root / "service/infrastructure/ide_bundle_files.py",
        "capsule_fixture_tests": root / "tests/test_ide_bundle_files.py",
    }
    sources = {}
    for name, path in paths.items():
        source = path.read_text(encoding="utf-8")
        sources[name] = (source, hashlib.sha256(source.encode()).hexdigest())
    # Exact new fixture only: no mounts, service restart, user workspaces or
    # package installation. The existing runtime image already includes Git.
    name = "gpthub-ide-capsule-fixture-" + uuid4().hex

    def remaining():
        query = subprocess.run(
            ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert query.returncode == 0, "ide_capsule_inventory_unavailable"
        return query.stdout.strip()

    assert not remaining(), "ide_capsule_fixture_name_occupied"
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--user",
                "65534:65534",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "256m",
                "--cpus",
                "0.5",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
                "--workdir",
                "/tmp",
                "-i",
                "--entrypoint",
                "python3",
                "gpthub-workspace-runtime:latest",
                "-I",
                "-",
            ],
            input=(f"SOURCES={sources!r}\n" + _PROBE).encode(),
            capture_output=True,
            timeout=40,
            check=False,
        )
    finally:
        if remaining():
            cleanup = subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False
            )
            assert cleanup.returncode == 0, "ide_capsule_fixture_cleanup_failed"
        assert not remaining(), "ide_capsule_fixture_remains"
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "ide_capsule_report_missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, "ide_capsule_failed_" + str(
        report.get("failures", report.get("stage", "unknown"))
    )
    assert report == {"status": "passed", "tests": 20, "skipped": 0, "failures": []}
