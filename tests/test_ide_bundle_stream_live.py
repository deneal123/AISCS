"""Opt-in source-injected sidecar -> two isolated Docker fixtures, no deployment."""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from application.ide_bundles import program_source

_PROBE = r"""
import asyncio,hashlib,importlib,io,json,shlex,sys,types
sys.path.insert(0,'/opt/workspace-sidecar/service')
stage='source_parity'
for name,(source,digest) in SOURCES.items():
    assert hashlib.sha256(source.encode()).hexdigest()==digest
    parent=importlib.import_module(name.rpartition('.')[0])
    try: module=importlib.import_module(name)
    except ModuleNotFoundError as error:
        assert error.name==name
        module=types.ModuleType(name);sys.modules[name]=module
    module.__file__='/exact-source-probe/'+name.replace('.','/')+'.py'
    setattr(parent,name.rpartition('.')[2],module)
    exec(compile(source,module.__file__,'exec'),module.__dict__)
from application.ide_bundles import IdeBundleService
from drivers.binary_exec import BinaryExecCancelled,BinaryExecFailure
from drivers.docker_cli import DockerCliDriver,_docker
from domain.policy import WorkspacePolicy
from infrastructure.ide_bundle_format import BundleFailure,BundleLimits
import drivers.docker_cli as module
import drivers.binary_exec as binary_module
original_argv=module._create_argv
def fixture_argv(*args,**kwargs):
    return ['gpthub.workspace=0' if part=='gpthub.workspace=1' else part
            for part in original_argv(*args,**kwargs)]
module._create_argv=fixture_argv
limits=BundleLimits(128,4*1024*1024,8*1024*1024,16*1024*1024,512*1024,16)
body=b'\x00\xffBINARY_FIXTURE'*140000

async def main():
    global stage
    driver=DockerCliDriver(); refs=[]; task=None; checks=0
    policy=WorkspacePolicy(exec_timeout_sec=15)
    try:
        stage='isolated_fixture_create'
        for identity in IDENTITIES:
            refs.append(await driver.create(identity,policy))
        items=[types.SimpleNamespace(ref=ref,policy=policy) for ref in refs]
        service=IdeBundleService(driver,source=PROGRAM)
        init="import pathlib,sys,os;r=pathlib.Path('/workspace');(r/'src').mkdir();(r/'src/main.py').write_text('print(42)\\n');(r/'binary').write_bytes(sys.stdin.buffer.read());os.link(r/'binary',r/'binary-copy');(r/'src/link').symlink_to('../binary');(r/'json.py').write_text('raise RuntimeError(\"REPO_IMPORT\")')"
        result=await driver.exec_with_input(refs[0],'python3 -I -c '+shlex.quote(init),payload=body,
                                            timeout_sec=10,max_output_chars=100)
        assert result.exit_code==0
        checks+=1
        stage='background_mutator_is_busy_not_killed'
        code,out,_=await _docker('exec',refs[0].container_id,'python3','-I','-c',
            "import subprocess;print(subprocess.Popen(['sleep','20'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True).pid)")
        assert code==0
        sleeper=int(out.strip());assert sleeper>1
        try:
            async with service.capture(items[0],limits): assert False
        except BundleFailure as error: assert error.code=='ide_bundle_busy'
        code,out,_=await _docker('exec',refs[0].container_id,'python3','-I','-c',
            "import os,signal;pid="+str(sleeper)+";assert open('/proc/'+str(pid)+'/cmdline','rb').read()==b'sleep\\x0020\\x00';os.kill(pid,signal.SIGTERM);print('stopped')")
        assert code==0 and out.strip()=='stopped'
        checks+=1
        stage='capture_binary_stream'
        async with service.capture(items[0],limits) as source:
            assert source._rolled and not source.closed
            capsule=source.read()
        assert source.closed and len(capsule)>1024*1024
        digest=hashlib.sha256(capsule).hexdigest()
        checks+=1
        stage='protected_http_capture'
        import time,httpx
        from contextlib import asynccontextmanager
        from dataclasses import asdict
        from fastapi import FastAPI,HTTPException
        from fastapi.responses import JSONResponse
        from presentation.routes.dependencies import WorkspaceRouteDependencies
        from presentation.routes.ide_capture import create_ide_capture_router
        item=items[0];item.expires_at=int(time.time())+60;item.expired=lambda: item.expires_at<=time.time()
        locked=False;guards=0;deny_after=False
        @asynccontextmanager
        async def operation(value):
            nonlocal locked
            assert value is item and not locked
            locked=True
            try:yield
            finally:locked=False
        async def guard(*args,**kwargs):
            nonlocal guards
            assert locked and args[1]=='snapshot'
            guards+=1
            return JSONResponse({},status_code=403) if deny_after and guards%2==0 else types.SimpleNamespace(allowed=True)
        def authorize(value):
            if value!='Bearer fixture':raise HTTPException(401)
        deps=WorkspaceRouteDependencies(authorize,lambda code,detail,status:JSONResponse({'error':code},status_code=status),
            lambda:types.SimpleNamespace(operation=operation,capture_ide=lambda target,bounds:service.capture_verified(target,bounds)),
            lambda identity,payload:(item,None) if identity==IDENTITIES[0] and payload.user_id=='fixture' and payload.token=='fixture' else (None,JSONResponse({},status_code=403)),
            guard,lambda result:isinstance(result,JSONResponse),None,None,None,None)
        app=FastAPI();app.include_router(create_ide_capture_router(deps))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as api:
            payload=dict(user_id='fixture',token='fixture',expected_expires_at=item.expires_at,coordination_capability='fixture',limits=asdict(limits))
            response=await api.post('/workspaces/'+IDENTITIES[0]+'/ide/capture',json=payload,headers={'Authorization':'Bearer fixture'})
            assert response.status_code==200 and len(response.content)==int(response.headers['content-length'])
            assert hashlib.sha256(response.content).hexdigest()==response.headers['x-ide-capsule-sha256']==digest
            assert response.content==capsule and guards==2 and not locked
            checks+=1
            stage='post_capture_denial_has_no_bytes'
            deny_after=True
            denied=await api.post('/workspaces/'+IDENTITIES[0]+'/ide/capture',json=payload,headers={'Authorization':'Bearer fixture'})
            assert denied.status_code==403 and 'x-ide-capsule-sha256' not in denied.headers
            assert capsule not in denied.content and guards==4 and not locked
            checks+=1
        stage='restore_fresh_runtime'
        stage='wire_digest_rejected_before_target_write'
        wrong=json.dumps(dict(root='/workspace',operation='restore',limits={name:getattr(limits,name) for name in limits.__dataclass_fields__},input_size=len(capsule),input_sha256='0'*64,timeout=10)).encode()+b'\n'
        async with driver.exec_binary(refs[1],PROGRAM,header=wrong,source=io.BytesIO(capsule),
                                      input_size=len(capsule),output_limit=0,timeout=10) as reply:
            assert reply.exit_code==65
            assert json.loads(reply.diagnostic)==dict(status='error',code='ide_bundle_changed')
        code,out,_=await _docker('exec',refs[1].container_id,'python3','-I','-c',"import os;print(len(os.listdir('/workspace')))")
        assert code==0 and out.strip()=='0'
        checks+=1
        stage='truncated_wire_never_starts_materialization'
        valid_header=json.dumps(dict(root='/workspace',operation='restore',limits={name:getattr(limits,name) for name in limits.__dataclass_fields__},input_size=len(capsule),input_sha256=digest,timeout=10)).encode()+b'\n'
        try:
            async with driver.exec_binary(refs[1],PROGRAM,header=valid_header,source=io.BytesIO(capsule[:-1]),
                                          input_size=len(capsule),output_limit=0,timeout=10): assert False
        except BinaryExecFailure as error:
            assert error.code=='binary_exec_input' and error.settled
        code,out,_=await _docker('exec',refs[1].container_id,'python3','-I','-c',"import os;print(len(os.listdir('/workspace')))")
        assert code==0 and out.strip()=='0'
        checks+=1
        stage='restore_fresh_runtime'
        restored=await service.restore(items[1],io.BytesIO(capsule),limits,
            expected_size=len(capsule),expected_sha256=digest)
        stage='restore_entry_count'
        assert restored==6
        inspect="import pathlib,hashlib,json,os;r=pathlib.Path('/workspace');print(json.dumps(dict(digest=hashlib.sha256((r/'binary').read_bytes()).hexdigest(),linked=(r/'binary').stat().st_ino==(r/'binary-copy').stat().st_ino,symlink=os.readlink(r/'src/link'),text=(r/'src/main.py').read_text())))"
        async def inspect_ref(ref):
            code,out,_=await _docker('exec',ref.container_id,'python3','-I','-c',inspect)
            assert code==0
            return json.loads(out)
        expected=dict(digest=hashlib.sha256(body).hexdigest(),linked=True,symlink='../binary',text='print(42)\n')
        stage='restore_contents'
        assert await inspect_ref(refs[1])==expected
        checks+=1
        stage='existing_runtime_not_overwritten'
        try:
            await service.restore(items[1],io.BytesIO(capsule),limits,
                expected_size=len(capsule),expected_sha256=digest)
            assert False
        except BundleFailure as error: assert error.code=='ide_bundle_target_not_empty'
        assert await inspect_ref(refs[1])==expected
        checks+=1
        stage='published_identity_rejected_before_restore'
        try:
            await service.restore(items[1],io.BytesIO(capsule),limits,
                expected_size=len(capsule),expected_sha256='0'*64)
            assert False
        except BundleFailure as error: assert error.code=='ide_bundle_invalid'
        checks+=1
        # Deterministically hold only capture(), retaining the exact current
        # watchdog/framing implementation. No daemon/remote process replacement.
        def blocked_program(marker):
            replacement=("import pathlib,time,os\n"
                "def _blocked(root,target,limits):\n"
                " pathlib.Path(root,'"+marker+"').touch()\n"
                + (" os.write(1,b'R')\n" if marker=='cancel-started' else '') +
                " while True: time.sleep(.05)\n"
                "sys.modules['infrastructure.ide_bundle_runtime'].capture_bundle=_blocked\n"
                "sys.modules['infrastructure.ide_bundle_runtime'].main()\n")
            return PROGRAM.replace("sys.modules['infrastructure.ide_bundle_runtime'].main()\n",replacement)
        def header(timeout):
            return json.dumps(dict(root='/workspace',operation='capture',limits=limits.__dict__ if hasattr(limits,'__dict__') else {name:getattr(limits,name) for name in limits.__dataclass_fields__},input_size=0,input_sha256=None,timeout=timeout)).encode()+b'\n'
        stage='remote_helper_cancellation'
        block=blocked_program('cancel-started')
        entered=asyncio.Event(); loop=asyncio.get_running_loop()
        original_receive=binary_module._receive
        async def observed_receive(stream,target,maximum):
            class Observed:
                def write(self,data):
                    written=target.write(data)
                    if data==b'R': loop.call_soon_threadsafe(entered.set)
                    return written
            return await original_receive(stream,Observed(),maximum)
        binary_module._receive=observed_receive
        async def invoke():
            async with driver.exec_binary(refs[0],block,header=header(15),source=None,input_size=0,
                                          output_limit=limits.archive_bytes,timeout=15): pass
        task=asyncio.create_task(invoke())
        try:
            await asyncio.wait_for(entered.wait(),5)
            task.cancel()
            try: await task;assert False
            except BinaryExecCancelled as error: assert error.settled
        finally:
            binary_module._receive=original_receive
        # Verify remote /proc, not merely termination of its Docker client.
        probe="import pathlib,hashlib;wanted='"+hashlib.sha256(block.encode()).hexdigest()+"';found=[]\nfor p in pathlib.Path('/proc').iterdir():\n if p.name.isdigit():\n  try:\n   a=(p/'cmdline').read_bytes().split(b'\\0')\n   if len(a)>3 and a[1:3]==[b'-I',b'-c'] and hashlib.sha256(a[3]).hexdigest()==wanted:found.append(p.name)\n  except OSError:pass\nprint(len(found))"
        code,out,_=await _docker('exec',refs[0].container_id,'python3','-I','-c',probe)
        assert code==0 and out.strip()=='0'
        checks+=1
        stage='sibling_runtime_survives'
        assert await inspect_ref(refs[1])==expected
        checks+=1
        stage='worker_independent_deadline'
        async with driver.exec_binary(refs[0],blocked_program('deadline-started'),header=header(.2),
                                      source=None,input_size=0,output_limit=1,timeout=5) as reply:
            assert reply.exit_code==65 and reply.size==0
            assert json.loads(reply.diagnostic)==dict(status='error',code='ide_bundle_unavailable')
        checks+=1
    finally:
        if task is not None and not task.done():
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        for ref in refs: await driver.destroy(ref)
    return checks
try:
    checks=asyncio.run(main())
    print(json.dumps(dict(status='passed',checks=checks)))
except BaseException as error:
    code=error.code if isinstance(error,BundleFailure) else type(error).__name__
    print(json.dumps(dict(status='failed',stage=stage,code=code)))
    raise SystemExit(1)
"""


def test_bundle_stream_probe_parses_without_execution():
    ast.parse(_PROBE)


@pytest.mark.skipif(
    os.getenv("IDE_LIVE_BUNDLE_STREAMS") != "1", reason="explicit isolated Docker stream acceptance"
)
def test_current_capsule_stream_between_two_isolated_runtimes():
    root = Path(__file__).resolve().parents[1]
    names = [
        "drivers.binary_exec",
        "drivers.docker_cli",
        "infrastructure.ide_bundle_format",
        "infrastructure.ide_bundle_files",
        "infrastructure.ide_restore_receipt",
        "infrastructure.ide_bundle_runtime",
        "application.ide_bundles",
        "presentation.routes.ide_capture",
    ]
    sources = {}
    for name in names:
        source = (root / "service" / (name.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        sources[name] = (source, hashlib.sha256(source.encode()).hexdigest())
    identities = [uuid4().hex, uuid4().hex]
    header = f"SOURCES={sources!r}\nIDENTITIES={identities!r}\nPROGRAM={program_source()!r}\n"
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", "gpthub-dev-workspace-1", "python3", "-"],
            input=(header + _PROBE).encode(),
            capture_output=True,
            timeout=55,
            check=False,
        )
    finally:
        for identity in identities:
            name = "gpthub-ws-" + identity
            query = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            assert query.returncode == 0, "ide_stream_fixture_inventory_unknown"
            if query.stdout.strip():
                cleanup = subprocess.run(
                    ["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False
                )
                assert cleanup.returncode == 0, "ide_stream_fixture_cleanup_failed"
            remaining = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=^/{name}$"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            assert remaining.returncode == 0 and not remaining.stdout.strip(), (
                "ide_stream_fixture_remains"
            )
    reports = [line for line in result.stdout.decode().splitlines() if line.startswith("{")]
    assert reports, "ide_stream_report_missing"
    report = json.loads(reports[-1])
    assert result.returncode == 0, (
        "ide_stream_failed_" + report.get("stage", "unknown") + ":" + report.get("code", "unknown")
    )
    assert report == {"status": "passed", "checks": 13}
