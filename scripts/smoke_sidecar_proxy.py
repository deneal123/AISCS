"""Opt-in Linux dev proof that internal HTTP authorization bypasses ambient proxies."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "agents": "gpthub-dev-agents-1",
    "backend": "gpthub-dev-backend-1",
}

# An isolated child process modifies only its own environment. It uses fake auth,
# two loopback servers and the real installed client, never a provider or service key.
PROBE = r"""
import asyncio, hashlib, importlib, json, os, pathlib, sys
from service.infrastructure.sidecar import SidecarClient
import service.infrastructure.sidecar as module

async def main():
    expected = json.load(sys.stdin)
    actual = hashlib.sha256(pathlib.Path(module.__file__).read_bytes()).hexdigest()
    if actual != expected['source_sha256']:
        raise RuntimeError('source_mismatch')
    operation_module = importlib.import_module(expected['operation_module'])
    operation_digest = hashlib.sha256(pathlib.Path(operation_module.__file__).read_bytes()).hexdigest()
    if operation_digest != expected['operation_sha256']:
        raise RuntimeError('source_mismatch')
    requests = {'target': [], 'proxy': []}
    async def respond(reader, writer, role):
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 2)
            requests[role].append(request)
            body = b'{"workspace_id":"fixture","token":"fake"}' if b' /workspaces ' in request else b'{"ok":true}'
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                         + b'Content-Length: ' + str(len(body)).encode()
                         + b'\r\nConnection: close\r\n\r\n' + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    target = await asyncio.start_server(lambda r,w: respond(r,w,'target'), '127.0.0.1', 0)
    proxy = await asyncio.start_server(lambda r,w: respond(r,w,'proxy'), '127.0.0.1', 0)
    try:
        proxy_url = 'http://127.0.0.1:' + str(proxy.sockets[0].getsockname()[1])
        for name in ('HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy'):
            os.environ[name] = proxy_url
        os.environ['NO_PROXY'] = os.environ['no_proxy'] = ''
        client = SidecarClient(service='probe', timeout=3,
            base_url='http://127.0.0.1:' + str(target.sockets[0].getsockname()[1]))
        result = await client.request_json('GET', '/health',
            headers={'Authorization': 'Bearer FAKE_PROXY_BOUNDARY_KEY'})
        assert result == {'ok': True}
        if expected['service'] == 'agents':
            assert await operation_module.acquire_video(client, {}, 'FAKE_PROXY_BOUNDARY_KEY') == {'ok': True}
        else:
            created = await operation_module._create(client._base, 'FAKE_PROXY_BOUNDARY_KEY', 3, 'fixture', 60)
            assert created == {'workspace_id': 'fixture', 'token': 'fake'}
        assert not requests['proxy']
        assert len(requests['target']) == 2
        assert all(b'Bearer FAKE_PROXY_BOUNDARY_KEY' in request for request in requests['target'])
    finally:
        target.close()
        proxy.close()
        await target.wait_closed()
        await proxy.wait_closed()
    print(json.dumps({'status': 'passed', 'proxy_requests': 0, 'target_requests': 2}))

try:
    asyncio.run(main())
except BaseException:
    print(json.dumps({'status': 'failed'}))
    sys.exit(1)
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    for service, container in TARGETS.items():
        try:
            source = ROOT / service / "service/infrastructure/sidecar.py"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            operation = "video_stream" if service == "agents" else "workspace_client"
            operation_file = ROOT / service / f"service/infrastructure/{operation}.py"
            operation_digest = hashlib.sha256(operation_file.read_bytes()).hexdigest()
            result = subprocess.run(
                ["docker", "exec", "-i", container, "python", "-c", PROBE],
                input=json.dumps(
                    {
                        "source_sha256": digest,
                        "service": service,
                        "operation_module": f"service.infrastructure.{operation}",
                        "operation_sha256": operation_digest,
                    }
                ),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            report = json.loads(result.stdout)
            passed = result.returncode == 0 and report == {
                "status": "passed",
                "proxy_requests": 0,
                "target_requests": 2,
            }
        except (OSError, subprocess.TimeoutExpired, ValueError):
            passed = False
        print(
            json.dumps({"service": service, "status": "passed" if passed else "failed"})
        )
        if not passed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
