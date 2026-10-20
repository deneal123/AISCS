"""Opt-in real Engine/sandbox lifecycle; no backend job, provider, or user project."""

import json
import os
import subprocess

import pytest

PROBE = r"""
import asyncio,json,uuid
from drivers.docker_cli import DockerCliDriver
from domain.policy import WorkspacePolicy
async def main():
    driver= DockerCliDriver()
    ref=await driver.create('cmd-probe-'+uuid.uuid4().hex,WorkspacePolicy(image='gpthub-workspace-runtime:harness-dev'))
    try:
        await driver.verify_isolation(ref,WorkspacePolicy(image='gpthub-workspace-runtime:harness-dev'))
        async def start(argv,timeout=5,limit=20000):
            operation=uuid.uuid4()
            engine=await driver.create_command(ref,operation)
            ready=await driver.ready_command(ref,operation,engine)
            assert ready['pid']>1
            await driver.dispatch_command(ref,operation,engine,argv=argv,timeout_sec=timeout,output_limit=limit)
            return operation,engine,ready
        async def result(operation,engine,ready):
            async with asyncio.timeout(20):
                while True:
                    value=await driver.command_status(ref,operation,engine,supervisor=ready)
                    if not value['running'] and value['receipt'] is not None:
                        return value
                    await asyncio.sleep(.05)
        item=await start(['python3','-c',"print('hello world')"])
        value=await result(*item)
        assert value['cleanup_confirmed'] and value['receipt']['result']['stdout']=='hello world\n'
        item=await start(['python3','-c',"print('x'*1000000)"],limit=100)
        value=await result(*item)
        assert value['receipt']['result']['truncated'] and len(value['receipt']['result']['stdout'])==100
        item=await start(['python3','-c','import time;time.sleep(60)'],timeout=.2)
        value=await result(*item)
        assert value['cleanup_confirmed'] and value['receipt']['result']['timed_out']
        item=await start(['python3','-c',"import subprocess; subprocess.Popen(['sleep','60'],start_new_session=True); print('parent exited')"])
        value=await result(*item)
        assert value['cleanup_confirmed'] and value['receipt']['result']['exit_code']==0
        item=await start(['python3','-c','import time;time.sleep(60)'],timeout=60)
        value=await driver.stop_command(ref,item[0],item[1],supervisor=item[2])
        assert value['cleanup_confirmed'] and not value['running']
        fresh=DockerCliDriver()
        value=await fresh.command_status(ref,item[0],item[1],supervisor=item[2])
        assert value['cleanup_confirmed'] and value['receipt'] is None
        print(json.dumps({'cases':6,'sandbox_removed':True}))
    finally:
        await driver.destroy(ref)
asyncio.run(main())
"""


@pytest.mark.skipif(
    os.getenv("IDE_COMMAND_DRIVER_LIVE") != "1", reason="explicit sandbox exec opt-in"
)
def test_real_addressable_exec_stop_and_detached_descendant_cleanup():
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python", "-c", PROBE],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("command_driver_live_probe_timeout", pytrace=False)
    # Do not echo exception/daemon payloads or command output into test diagnostics.
    assert result.returncode == 0, "command_driver_live_probe_failed"
    assert json.loads(result.stdout) == {"cases": 6, "sandbox_removed": True}
