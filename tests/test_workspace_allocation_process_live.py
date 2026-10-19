"""Opt-in: two owned Docker allocations survive an actual interpreter exit."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

_MODULES = {
    "domain.policy": "domain/policy.py",
    "application.recovery": "application/recovery.py",
    "application.allocations": "application/allocations.py",
    "drivers.docker_cli": "drivers/docker_cli.py",
    "application.lifecycle": "application/lifecycle.py",
    "infrastructure.ide_read_runtime": "infrastructure/ide_read_runtime.py",
    "application.ide_reads": "application/ide_reads.py",
}

_PROBE = r"""
import asyncio, hashlib, importlib, json, os, sys, types, uuid
sys.path.insert(0, '/opt/workspace-sidecar/service')
stage = 'source_parity'
for name, source in SOURCES.items():
    assert hashlib.sha256(source.encode()).hexdigest() == DIGESTS[name]
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as missing:
        assert missing.name == name
        importlib.import_module(name.rpartition('.')[0])
        module = types.ModuleType(name)
        module.__file__ = '/opt/workspace-sidecar/service/' + name.replace('.', '/') + '.py'
        sys.modules[name] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
from application.allocations import WorkspaceAllocation
from application.lifecycle import WorkspaceRegistry
from application.ide_reads import IdeReadService
from application.recovery import LABEL_MANIFEST, parse_manifest, owner_binding
from domain.ownership import verify
from domain.policy import WorkspacePolicy
from domain.files import write_command, read_command, parse_read
from drivers.base import ContainerRef, ManagedContainer
from drivers.docker_cli import DockerCliDriver, _docker
import drivers.docker_cli as driver_module

# These containers belong exclusively to the probe's registries, not the
# running service's background inventory/reaper. All policy flags stay intact.
native_argv = driver_module._create_argv
def fixture_argv(*args, **kwargs):
    return ['gpthub.workspace=0' if value == 'gpthub.workspace=1' else value
        for value in native_argv(*args, **kwargs)]
driver_module._create_argv = fixture_argv

owner = 'ide-allocation-fixture-' + MARKER
allocations = [WorkspaceAllocation(uuid.UUID(value), DEADLINE) for value in INTENTS]
identities = [value.workspace_id(owner) for value in allocations]
assert len(set(identities)) == 2 and all(len(value) == 32 for value in identities)

class Driver(DockerCliDriver):
    create_calls = 0
    async def create(self, *args, **kwargs):
        self.create_calls += 1
        return await super().create(*args, **kwargs)
    async def list_managed(self):
        found = []
        for identity in identities:
            code, raw, _ = await _docker('ps', '-aq', '--no-trunc',
                '--filter', 'name=^/gpthub-ws-' + identity + '$')
            assert code == 0
            for container_id in raw.splitlines():
                code, details, _ = await _docker('inspect', container_id)
                assert code == 0
                labels = json.loads(details)[0]['Config']['Labels']
                manifest = parse_manifest(labels.get(LABEL_MANIFEST))
                assert manifest is not None and manifest.workspace_id == identity
                assert manifest.owner_binding == owner_binding(identity, owner)
                found.append(ManagedContainer(ContainerRef(self.name, container_id), labels))
        return found

async def main():
    global stage
    driver = Driver()
    registry = WorkspaceRegistry(driver, max_workspaces=2)

    async def run_reader(item, command, *, stdin_payload):
        return await registry.exec_raw(item, command, max_output_chars=1700000,
            stdin_payload=stdin_payload)

    reader = IdeReadService(run_reader, program_source=SOURCES['infrastructure.ide_read_runtime'])
    if MODE == 'cleanup':
        stage = 'fixture_cleanup'
        for container in await driver.list_managed():
            await driver.destroy(container.ref)
        assert not await driver.list_managed()
        return {'status':'cleaned'}
    if MODE == 'prepare':
        stage = 'isolated_allocation'
        policy = WorkspacePolicy(memory_bytes=134217728, quota_bytes=8388608,
            pids_limit=64, cpus=0.5)
        for index, allocation in enumerate(allocations):
            stage = 'container_create'
            item, _ = await registry.create(owner, policy, allocation=allocation)
            stage = 'fixture_write'
            command, body = write_command(item.policy.root, 'allocation-proof.txt', str(index))
            result = await registry.exec_raw(item, command, max_output_chars=4096,
                stdin_payload=body)
            assert '__OK__' in result.stdout
        assert driver.create_calls == 2 and registry.count() == 2
        print(json.dumps({'status':'prepared'}), flush=True)
        os._exit(0)  # Real process loss: no Python cleanup or retained registry.
    stage = 'signed_recovery'
    assert await registry.reconcile() == 2
    items = []
    for index, allocation in enumerate(allocations):
        item = registry.lookup_allocation(owner, allocation)
        assert item is not None and item.recovered
        assert item.workspace_id == identities[index] and item.expires_at == DEADLINE
        assert registry.lookup_allocation(owner + '-other', allocation) is None
        verify(registry.allocation_token(item, owner), item.workspace_id, owner)
        result = await registry.exec_raw(item, read_command(item.policy.root, 'allocation-proof.txt'),
            max_output_chars=4096)
        content, truncated = parse_read(result.stdout)
        assert content == str(index) and not truncated
        stage = 'owned_ide_reads'
        observed = await reader.read(item, operation='file', path='allocation-proof.txt')
        assert observed['content'] == str(index) and not observed['truncated']
        assert observed['digest'] == hashlib.sha256(str(index).encode()).hexdigest()
        tree = await reader.read(item, operation='tree', path='')
        assert tree == {'entries':[{'path':'allocation-proof.txt','type':'file','size':1}],
            'truncated':False}
        replayed, _ = await registry.create(owner, item.policy, allocation=allocation)
        assert replayed is item
        items.append(item)
    assert driver.create_calls == 0 and len(await driver.list_managed()) == 2
    stage = 'independent_retirement'
    await registry.destroy(items[0].workspace_id)
    assert registry.lookup_allocation(owner, allocations[1]) is items[1]
    assert len(await driver.list_managed()) == 1
    await registry.destroy(items[1].workspace_id)
    assert registry.count() == 0 and not await driver.list_managed()
    return {'status':'passed','checks':{'separate_process':True,'files_isolated':True,
        'no_reallocation':True,'fixed_expiry':True,'containers_removed':True}}

try:
    print(json.dumps(asyncio.run(main())))
except BaseException as error:
    category = type(error).__name__
    if category not in {'DriverError','IsolationUnverified','AssertionError',
        'TypeError','ValueError','RuntimeError','AttributeError'}:
        category = 'other'
    print(json.dumps({'status':'failed','stage':stage,'category':category}))
    raise SystemExit(1)
"""


def test_allocation_process_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("S37_LIVE_WORKSPACE_ALLOCATIONS") != "1",
    reason="explicit isolated two-process Docker allocation acceptance",
)
def test_two_repositories_keep_independent_containers_files_and_recovered_identity():
    import time

    root = Path(__file__).resolve().parents[1] / "service"
    sources = {name: (root / path).read_text(encoding="utf-8") for name, path in _MODULES.items()}
    digests = {
        name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()
    }
    marker = uuid4().hex
    intents = [str(uuid4()), str(uuid4())]
    deadline = int(time.time()) + 120

    def run(mode):
        header = (
            f"SOURCES={sources!r}\nDIGESTS={digests!r}\nMARKER={marker!r}\n"
            f"INTENTS={intents!r}\nDEADLINE={deadline}\nMODE={mode!r}\n"
        )
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
            input=(header + _PROBE).encode(),
            capture_output=True,
            timeout=45,
            check=False,
        )
        reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
        assert reports, "allocation_process_report_missing"
        report = json.loads(reports[-1])
        assert result.returncode == 0, (
            "allocation_process_failed_"
            + str(report.get("stage", "unknown"))
            + "_"
            + str(report.get("category", "unknown"))
        )
        return report

    try:
        assert run("prepare") == {"status": "prepared"}
        assert run("recover") == {
            "status": "passed",
            "checks": {
                "separate_process": True,
                "files_isolated": True,
                "no_reallocation": True,
                "fixed_expiry": True,
                "containers_removed": True,
            },
        }
    finally:
        assert run("cleanup") == {"status": "cleaned"}
