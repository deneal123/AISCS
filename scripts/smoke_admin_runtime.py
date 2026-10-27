"""Opt-in dev installed-code checks without touching provider keys or memory.

Faults run in isolated Python interpreters inside existing containers. This is
not authenticated admin UI acceptance or a real provider rotation test.
"""

from __future__ import annotations

import hashlib
import json

from smoke_workspace_restart import (
    BACKEND,
    COMPOSE,
    ROOT,
    WORKERS,
    ProbeFailure,
    decoded,
    idle,
)

FILES = (
    "service/services/admin/application/admin_service.py",
    "service/services/admin/application/provider_key_service.py",
    "service/services/admin/application/runtime_settings.py",
)

PROBE = r"""
import asyncio, hashlib, importlib, json, logging, sys
from unittest.mock import AsyncMock, Mock, patch

async def probe():
    from service.services.admin.application import admin_service as admin
    from service.services.admin.application import provider_key_service as keys
    from service.services.admin.application import runtime_settings as settings
    from service.infrastructure.agents_client import engine_factory, sidecar_providers
    paths=json.load(sys.stdin)
    observed={}
    for relative in paths:
        module=importlib.import_module(relative[:-3].replace('/', '.'))
        with open(module.__file__, 'rb') as handle:
            observed[relative]=hashlib.sha256(handle.read()).hexdigest()
    records=[]
    class Capture(logging.Handler):
        def emit(self, record): records.append(record)
    marker='admin-runtime-private-sentinel'
    handler=Capture()
    for module in (admin, keys, settings):
        module.logger.handlers=[handler]
        module.logger.propagate=False
        module.logger.setLevel(logging.DEBUG)
    service=admin.AdminService(
        Mock(fetch_is_admin=AsyncMock(side_effect=RuntimeError(marker))),
        Mock(get_all=AsyncMock(side_effect=RuntimeError(marker))),
        Mock(invalidate=AsyncMock(side_effect=RuntimeError(marker))),
    )
    with patch.object(service, 'is_env_admin', return_value=False):
        assert await service.is_admin(marker) is False
    await service._invalidate_profile_cache(marker, marker)
    view=await service.get_settings_view()
    assert view['settings'] and all(not item['overridden'] for item in view['settings'])
    key_service=keys.ProviderKeyService(
        Mock(get_all=AsyncMock(side_effect=RuntimeError(marker)))
    )
    push=AsyncMock(return_value=True)
    with patch.object(engine_factory, 'uses_http_engine', return_value=True), \
         patch.object(sidecar_providers, 'fetch_keys_version', AsyncMock(return_value=1)), \
         patch.object(sidecar_providers, 'push_provider_keys', push):
        assert await key_service.ensure_sidecar_keys(version=2) is False
    push.assert_not_awaited()
    runtime=settings.RuntimeSettings()
    runtime.bind(Mock(get_all=AsyncMock(side_effect=RuntimeError(marker))))
    runtime._cache={'fixture': 'retained'}
    await runtime.refresh(force=True)
    assert runtime._cache=={'fixture': 'retained'}
    assert len(records)==5
    for record in records:
        assert record.exc_info is None
        assert record.failure_code=='unavailable'
        assert marker not in str(record.__dict__)
    # Exercise installed lifecycle helpers with private fake repositories, not DB writes.
    runtime=settings.RuntimeSettings()
    release=asyncio.Event()
    async def pending():
        await release.wait()
        return {'agents.max_subtasks':4}
    repository=Mock(get_all=AsyncMock(side_effect=pending))
    runtime.bind(repository)
    for _ in range(100):
        assert runtime.get_agents('max_subtasks',3)==3
    task=runtime._refresh_task
    await asyncio.sleep(0)
    assert repository.get_all.await_count==1
    release.set()
    await task
    assert runtime._refresh_task is None
    assert runtime.get_agents('max_subtasks',3)==4
    for action in ('invalidate','rebind'):
        runtime=settings.RuntimeSettings()
        entered,release=asyncio.Event(),asyncio.Event()
        async def old_snapshot():
            entered.set()
            await release.wait()
            return {'agents.max_subtasks':1}
        repository=Mock(get_all=AsyncMock(side_effect=old_snapshot))
        runtime.bind(repository)
        runtime._cache={'agents.max_subtasks':3}
        task=asyncio.create_task(runtime.refresh(force=True))
        await entered.wait()
        replacement=Mock(get_all=AsyncMock(return_value={'agents.max_subtasks':5}))
        if action=='invalidate':
            runtime.invalidate()
            repository.get_all.side_effect=None
            repository.get_all.return_value={'agents.max_subtasks':5}
        else:
            runtime.bind(replacement)
        release.set()
        await task
        assert runtime._cache=={'agents.max_subtasks':3}
        assert runtime._expires_at==0
        await runtime.refresh()
        assert runtime.get_agents('max_subtasks',3)==5
    return {'digests': observed, 'cases':8, 'safe_records':len(records),
            'secret_pushes':push.await_count, 'real_mutations':0}

try:
    print(json.dumps(asyncio.run(probe())))
except BaseException:
    print(json.dumps({'status':'failed','stage':'installed_admin_probe'}))
    raise SystemExit(1)
"""


def configuration_matches() -> None:
    desired = decoded([*COMPOSE, "config", "--format", "json"], "compose_config")
    for container, service in (
        (BACKEND, "backend"),
        *(
            (name, name.removeprefix("gpthub-dev-").removesuffix("-1"))
            for name, _ in WORKERS
        ),
    ):
        inspected = decoded(["docker", "inspect", container], "inspect")
        actual = dict(value.split("=", 1) for value in inspected[0]["Config"]["Env"])
        expected = desired["services"][service]["environment"]
        if any(actual.get(key) != str(value) for key, value in expected.items()):
            raise ProbeFailure("configuration_changed")


def run() -> dict:
    configuration_matches()
    idle_counts = idle()
    expected = {
        name: hashlib.sha256((ROOT / "backend" / name).read_bytes()).hexdigest()
        for name in FILES
    }
    results = []
    for container in (BACKEND, *(name for name, _ in WORKERS)):
        result = decoded(
            ["docker", "exec", "-i", container, "python", "-c", PROBE],
            "installed_admin_probe",
            data=json.dumps(FILES),
            timeout=30,
        )
        if not isinstance(result, dict) or result.get("digests") != expected:
            raise ProbeFailure("admin_source_mismatch")
        if (
            result.get("cases") != 8
            or result.get("safe_records") != 5
            or result.get("secret_pushes") != 0
            or result.get("real_mutations") != 0
        ):
            raise ProbeFailure("admin_probe_contract")
        results.append({"cases": 8, "source_matches": True, "secret_pushes": 0})
    # An installed-code check is distinct from the serving HTTP process's health.
    health = decoded(
        [
            "docker",
            "exec",
            BACKEND,
            "python",
            "-c",
            "import json,urllib.request; "
            "r=urllib.request.urlopen('http://localhost:8000/api/health', timeout=15); "
            "print(json.dumps({'status':r.status}))",
        ],
        "backend_health",
        timeout=20,
    )
    if not isinstance(health, dict) or health.get("status") != 200:
        raise ProbeFailure("backend_health")
    return {
        "status": "passed",
        "containers": len(results),
        "cases": 24,
        "source_matches": True,
        "secret_pushes": 0,
        "real_mutations": 0,
        "backend_http": 200,
        "idle": idle_counts,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run()))
    except Exception:
        print(json.dumps({"status": "failed", "stage": "admin_runtime_smoke"}))
        raise SystemExit(1) from None
