"""Real Docker inventory isolation, using current source without replacing dev."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

CONTAINER = "gpthub-dev-workspace-1"
PROBE = r"""
import asyncio, json, uuid
from domain.policy import WorkspacePolicy
from drivers.docker_cli import DockerCliDriver
from drivers.inventory import DockerInventory

async def main():
    marker = uuid.uuid4().hex
    policy = WorkspacePolicy(image='gpthub-workspace-runtime:harness-dev')
    drivers = [DockerCliDriver(inventory=DockerInventory('acceptance-'+marker+'-'+n))
               for n in ('a', 'b')]
    refs = []
    try:
        for i, driver in enumerate(drivers):
            ref = await driver.create('inventory-'+marker+'-'+str(i), policy)
            refs.append(ref)
            await driver.verify_isolation(ref, policy)
        for driver, ref in zip(drivers, refs):
            assert [item.ref for item in await driver.list_managed()] == [ref]
        default = await DockerCliDriver(inventory=DockerInventory()).list_managed()
        assert not set(refs) & {item.ref for item in default}
        operation = uuid.uuid4()
        driver, ref = drivers[0], refs[0]
        engine = await driver.create_command(ref, operation)
        ready = await driver.ready_command(ref, operation, engine)
        await driver.dispatch_command(ref, operation, engine,
            argv=['python3', '-c', "print('inventory isolated')"], timeout_sec=3,
            output_limit=1024)
        async with asyncio.timeout(15):
            while True:
                result = await driver.command_status(ref, operation, engine, supervisor=ready)
                if not result['running'] and result['receipt']:
                    break
                await asyncio.sleep(.05)
        assert result['cleanup_confirmed']
        assert result['receipt']['result']['stdout'] == 'inventory isolated\n'
        assert result['receipt']['result']['exit_code'] == 0
    finally:
        for driver, ref in zip(drivers, refs):
            await driver.destroy(ref)
    for driver in drivers:
        assert not await driver.list_managed()
    print(json.dumps({'inventories': 2, 'exec_verified': True, 'fixtures_removed': True}))

asyncio.run(main())
"""


def docker(*args, timeout=40, **kwargs):
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
        **kwargs,
    )
    if result.returncode:
        pytest.fail("scoped_workspace_probe_failed", pytrace=False)
    return result.stdout.strip()


@pytest.mark.skipif(os.getenv("WORKSPACE_INVENTORY_LIVE") != "1", reason="isolated Docker opt-in")
def test_current_source_scopes_real_inventory_without_changing_dev():
    temporary = docker("exec", CONTAINER, "mktemp", "-d", "/tmp/gpthub-harness-XXXXXXXX")
    assert re.fullmatch(r"/tmp/gpthub-harness-[A-Za-z0-9]{8}", temporary)
    source = Path(__file__).resolve().parents[1] / "service"
    try:
        docker("cp", str(source), f"{CONTAINER}:{temporary}/service")
        outcome = docker(
            "exec",
            "-w",
            temporary + "/service",
            CONTAINER,
            "python",
            "-c",
            PROBE,
            timeout=90,
        )
        assert json.loads(outcome) == {
            "inventories": 2,
            "exec_verified": True,
            "fixtures_removed": True,
        }
    finally:
        # Only the validated mktemp-owned source copy, never a project/data tree.
        docker(
            "exec",
            CONTAINER,
            "python",
            "-c",
            "import shutil,sys;shutil.rmtree(sys.argv[1])",
            temporary,
        )
