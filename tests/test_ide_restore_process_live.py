"""Opt-in exact-source restore staging across real interpreter loss; no deployment."""

import ast
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
from application.ide_bundles import program_source

MODULES = [
    "domain.policy",
    "application.recovery",
    "application.allocations",
    "drivers.binary_exec",
    "drivers.docker_cli",
    "infrastructure.ide_bundle_format",
    "infrastructure.ide_bundle_files",
    "infrastructure.ide_restore_receipt",
    "infrastructure.ide_bundle_runtime",
    "application.ide_bundles",
    "application.ide_restore",
    "application.lifecycle",
]

PROBE = r"""
import asyncio, hashlib, importlib, io, json, os, shlex, sys, types, uuid
sys.path.insert(0, '/opt/workspace-sidecar/service')
stage = 'source_parity'
for name, (source, digest) in SOURCES.items():
    stage = 'source_' + name
    assert hashlib.sha256(source.encode()).hexdigest() == digest
    parent = importlib.import_module(name.rpartition('.')[0])
    try: module = importlib.import_module(name)
    except ModuleNotFoundError as error:
        assert error.name == name
        module = types.ModuleType(name); sys.modules[name] = module
    module.__file__ = '/exact-source-probe/' + name.replace('.', '/') + '.py'
    setattr(parent, name.rpartition('.')[2], module)
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
from application.allocations import WorkspaceAllocation, AllocationPending
from application.lifecycle import WorkspaceRegistry
from application.ide_restore import IdeRestore
from application.recovery import LABEL_MANIFEST, parse_manifest, owner_binding, restore_receipt
from domain.policy import WorkspacePolicy
from drivers.base import ContainerRef, ManagedContainer
from drivers.docker_cli import DockerCliDriver, _docker
import drivers.docker_cli as driver_module
from infrastructure.ide_bundle_format import BundleLimits
from infrastructure.ide_restore_receipt import NAME
import application.ide_bundles as bundles
bundles.program_source = lambda: PROGRAM
owner = 'ide-restore-fixture-' + MARKER
allocations = [WorkspaceAllocation(uuid.UUID(value), DEADLINE) for value in INTENTS]
identities = [allocation.workspace_id(owner) for allocation in allocations]
policy = WorkspacePolicy(memory_bytes=134217728, quota_bytes=8388608, pids_limit=64, cpus=0.5)
limits = BundleLimits(128, 1024*1024, 4*1024*1024, 8*1024*1024, 512*1024, 16)
fixture_label = 'gpthub.ide.restore.fixture'
native_argv = driver_module._create_argv
def fixture_argv(*args, **kwargs):
    return ['gpthub.workspace=0' if value == 'gpthub.workspace=1' else value
            for value in native_argv(*args, **kwargs)]
driver_module._create_argv = fixture_argv

class Driver(DockerCliDriver):
    creates = 0
    async def create(self, *args, **kwargs):
        self.creates += 1
        kwargs['labels'] = {**kwargs.get('labels', {}), 'gpthub.workspace': '0', fixture_label: MARKER}
        return await super().create(*args, **kwargs)
    async def list_managed(self):
        code, raw, _ = await _docker('ps', '-aq', '--no-trunc', '--filter', 'label='+fixture_label+'='+MARKER)
        assert code == 0
        found = []
        for identity in raw.splitlines():
            code, details, _ = await _docker('inspect', identity)
            assert code == 0
            value = json.loads(details)[0]; labels = value['Config']['Labels']
            manifest = parse_manifest(labels.get(LABEL_MANIFEST))
            assert manifest is not None and manifest.workspace_id in identities
            assert labels.get(fixture_label) == MARKER and labels.get('gpthub.workspace') == '0'
            assert manifest.owner_binding == owner_binding(manifest.workspace_id, owner)
            found.append(ManagedContainer(ContainerRef(self.name, identity), labels))
        return found

async def main():
    global stage
    driver = Driver(); registry = WorkspaceRegistry(driver, max_workspaces=4)
    service = bundles.IdeBundleService(driver)
    async def execute(item, code, data=b''):
        result = await driver.exec_with_input(item.ref, 'python3 -I -c '+shlex.quote(code),
            payload=data, timeout_sec=10, max_output_chars=4096)
        assert result.exit_code == 0 and not result.timed_out and not result.truncated
        return result.stdout
    if MODE == 'cleanup':
        for item in await driver.list_managed(): await driver.destroy(item.ref)
        assert not await driver.list_managed()
        return dict(status='cleaned')
    if MODE == 'prepare':
        stage = 'source_allocation'
        source, _ = await registry.create(owner, policy, allocation=allocations[0])
        code = "import pathlib,subprocess; r=pathlib.Path('/workspace');(r/'main.py').write_text('print(42)\\n');(r/'empty').mkdir();(r/'binary').write_bytes(b'\\x00\\xff'*10000);g=['git','-c','core.hooksPath=/dev/null','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','-C',str(r)];subprocess.run(g+['init','-q'],check=True);subprocess.run(g+['add','.'],check=True);subprocess.run(g+['commit','-qm','fixture'],check=True);(r/'main.py').write_text('print(43)\\n')"
        await execute(source, code)
        stage = 'capture_selected_capsule'
        async with service.capture(source, limits) as stream: capsule = stream.read()
        digest = hashlib.sha256(capsule).hexdigest()
        async def restore(index):
            return await registry.create_restored(owner, policy, allocation=allocations[index],
                source=io.BytesIO(capsule), limits=limits, expected_size=len(capsule), expected_sha256=digest)
        stage = 'restore_confirmed_before_ready'
        completed, _ = await restore(1)
        stage = 'restored_snapshot_identity'
        assert completed.restore_snapshot.sha256 == digest
        stage = 'restored_contents'
        await execute(completed, "import pathlib;assert pathlib.Path('/workspace/main.py').read_text()=='print(43)\\n';assert pathlib.Path('/workspace/binary').read_bytes()==b'\\x00\\xff'*10000")
        labels = {value.ref: value.labels for value in await driver.list_managed()}
        completed_proof = restore_receipt(labels[completed.ref][LABEL_MANIFEST])
        entered = asyncio.Event()
        original = IdeRestore.initialize
        async def interrupted(self, selected_driver, item, manifest):
            if item.workspace_id == identities[3]:
                # Real full restore, but no lifecycle commit. Leave that stage
                # in flight while another initializer loses the whole process.
                await service.restore(item, self.source, self.limits,
                    expected_size=self.snapshot.size, expected_sha256=self.snapshot.sha256)
                wanted = restore_receipt(manifest)
                marker_path = '/tmp/'+NAME
                for fixture in ('fifo', 'symlink'):
                    setup = "import os,pathlib; p="+repr(marker_path)+";"
                    if fixture == 'fifo': setup += "os.mkfifo(p)"
                    else: setup += "pathlib.Path(p).symlink_to('/workspace/main.py')"
                    await execute(item, setup)
                    assert not await service.receipt(item, wanted, write=False)
                    await execute(item, "import os;os.unlink("+repr(marker_path)+")")
                # Another container's genuine completion proof is not valid here.
                await execute(item, "import pathlib,sys;pathlib.Path("+repr(marker_path)+").write_bytes(sys.stdin.buffer.read())", completed_proof.encode())
                assert not await service.receipt(item, wanted, write=False)
                entered.set()
                await asyncio.Event().wait()
            elif item.workspace_id == identities[2]:
                await execute(item, "import pathlib;pathlib.Path('/workspace/partial').write_text('incomplete')")
                for index in (2,3):
                    try: registry.lookup_allocation(owner, allocations[index]); assert False
                    except AllocationPending: pass
                assert registry.health()['active'] == 2 and registry.count() == 4
                print(json.dumps(dict(status='prepared')), flush=True)
                os._exit(0)
            else: await original(self, selected_driver, item, manifest)
        IdeRestore.initialize = interrupted
        task = asyncio.create_task(restore(3))
        await asyncio.wait_for(entered.wait(), 12)
        stage = 'process_exit_during_unpublished_initialization'
        await restore(2)
        assert False
    stage = 'restart_recovers_only_confirmed_restore'
    assert await registry.reconcile() == 2
    assert registry.count() == 2 and registry.health()['active'] == 2
    for index in (0,1):
        item = registry.lookup_allocation(owner, allocations[index])
        assert item is not None and item.recovered
        assert item.expires_at == DEADLINE
        assert registry.lookup_allocation(owner+'-other', allocations[index]) is None
        await execute(item, "import pathlib,subprocess;assert pathlib.Path('/workspace/main.py').read_text()=='print(43)\\n';assert pathlib.Path('/workspace/binary').read_bytes()==b'\\x00\\xff'*10000;assert subprocess.check_output(['git','-C','/workspace','log','-1','--format=%s']).strip()==b'fixture';assert b' M main.py' in subprocess.check_output(['git','-C','/workspace','status','--porcelain'])")
    restored = registry.lookup_allocation(owner, allocations[1])
    assert restored.restore_snapshot is not None
    # Lost acknowledgement recovery observes the selected identity, no new I/O.
    replay, _ = await registry.create_restored(owner, policy, allocation=allocations[1],
        source=io.BytesIO(b''), limits=limits, expected_size=restored.restore_snapshot.size,
        expected_sha256=restored.restore_snapshot.sha256)
    assert replay is restored and driver.creates == 0
    for index in (2,3): assert registry.lookup_allocation(owner, allocations[index]) is None
    remaining = await driver.list_managed()
    assert len(remaining) == 2
    for item in remaining: await registry.destroy(parse_manifest(item.labels[LABEL_MANIFEST]).workspace_id)
    assert not await driver.list_managed() and registry.count() == 0
    return dict(status='passed', checks=8)

try: print(json.dumps(asyncio.run(main())))
except BaseException as error:
    print(json.dumps(dict(status='failed',stage=stage,category=type(error).__name__)))
    raise SystemExit(1)
"""


def test_restore_process_probe_parses_without_execution():
    probe = ast.parse(PROBE)
    code = next(
        node.value.value
        for node in ast.walk(probe)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "code" for target in node.targets)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
    constants = [node.value for node in ast.walk(ast.parse(code)) if isinstance(node, ast.Constant)]
    assert b"\x00\xff" in constants and "print(43)\n" in constants


def cleanup_fixtures(marker):
    query = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=gpthub.ide.restore.fixture=" + marker],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert query.returncode == 0, "restore_fixture_inventory_unavailable"
    for identity in query.stdout.decode().splitlines():
        inspection = subprocess.run(
            ["docker", "inspect", identity], capture_output=True, timeout=10, check=False
        )
        assert inspection.returncode == 0, "restore_fixture_inspection_unavailable"
        value = json.loads(inspection.stdout)[0]
        assert value["Config"]["Labels"].get("gpthub.ide.restore.fixture") == marker
        assert value["Config"]["Labels"].get("gpthub.workspace") == "0"
        assert value["Name"].startswith("/gpthub-ws-") and value["Id"].startswith(identity)
        result = subprocess.run(
            ["docker", "rm", "-f", value["Id"]], capture_output=True, timeout=10, check=False
        )
        assert result.returncode == 0, "restore_fixture_cleanup_failed"
    remaining = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=gpthub.ide.restore.fixture=" + marker],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert remaining.returncode == 0 and not remaining.stdout.strip(), "restore_fixture_remains"


@pytest.mark.skipif(
    os.getenv("IDE_LIVE_RESTORE") != "1", reason="explicit isolated restore/process-loss acceptance"
)
def test_staged_restore_cannot_become_ready_after_real_process_loss():
    root = Path(__file__).resolve().parents[1] / "service"
    sources = {}
    for name in MODULES:
        source = (root / (name.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        sources[name] = source, hashlib.sha256(source.encode()).hexdigest()
    marker = uuid4().hex
    intents = [str(uuid4()) for _ in range(4)]
    deadline = int(time.time()) + 180

    def run(mode):
        header = f"SOURCES={sources!r}\nMARKER={marker!r}\nINTENTS={intents!r}\nDEADLINE={deadline}\nMODE={mode!r}\nPROGRAM={program_source()!r}\n"
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
            input=(header + PROBE).encode(),
            capture_output=True,
            timeout=55,
            check=False,
        )
        reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
        assert reports, "restore_process_report_missing"
        report = json.loads(reports[-1])
        assert result.returncode == 0, (
            "restore_process_failed_"
            + report.get("stage", "unknown")
            + "_"
            + report.get("category", "unknown")
        )
        return report

    try:
        assert run("prepare") == {"status": "prepared"}
        assert run("recover") == {"status": "passed", "checks": 8}
    finally:
        try:
            assert run("cleanup") == {"status": "cleaned"}
        finally:
            # The child may fail before loading any lifecycle source. Parent
            # cleanup still targets only this exact UUID-tagged fixture set.
            cleanup_fixtures(marker)
