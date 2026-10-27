"""Opt-in scoped dev sidecar recreate with a private owned HTTP recovery fixture."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / "docker/.env.dev"),
    "-p",
    "gpthub-dev",
    "-f",
    str(ROOT / "docker/docker-compose.dev.yaml"),
    "--profile",
    "dev",
    "--profile",
    "celery",
]
WORKSPACE = "gpthub-dev-workspace-1"
BACKEND = "gpthub-dev-backend-1"
WORKERS = (
    ("gpthub-dev-celery-worker-agents-1", "agent-worker"),
    ("gpthub-dev-celery-worker-maintenance-1", "maintenance-worker"),
)

_JOBS = """
import json,sys
from service.infrastructure.messaging.celery_app import celery_app
nodes=json.load(sys.stdin)
inspector=celery_app.control.inspect(destination=nodes,timeout=5)
report={'workers':len(nodes),'complete':True}
for category in ('active','reserved','scheduled'):
 reply=getattr(inspector,category)()
 valid=(isinstance(reply,dict) and set(reply)==set(nodes)
        and all(isinstance(tasks,list) for tasks in reply.values()))
 report['complete']=report['complete'] and valid
 report[category]=sum(len(tasks) for tasks in reply.values()) if valid else None
print(json.dumps(report))
"""

_HTTP = """
import json,os,sys,urllib.request,urllib.error,uuid
p=json.load(sys.stdin); mode=p['mode']
headers={'Authorization':'Bearer '+os.environ['AGENTS__WORKSPACE_API_KEY'],
 'Content-Type':'application/json'}
base='http://workspace:8080'
try:
 if mode=='validation':
  marker='restart-privacy-sentinel'
  data={'user_id':{'private':marker},'ttl_sec':marker}
  req=urllib.request.Request(base+'/workspaces',data=json.dumps(data).encode(),headers=headers)
  try:
   urllib.request.urlopen(req,timeout=30)
  except urllib.error.HTTPError as error:
   assert error.code==422
   raw=error.read(4097); error.close(); assert len(raw)<=4096
   body=json.loads(raw)
   assert body.get('error')=='invalid_request' and marker not in raw.decode()
  else: raise AssertionError('invalid_request_accepted')
  result={'invalid_request_redacted':True}
 elif mode=='create':
  owner='restart-acceptance-'+uuid.uuid4().hex
  data={'user_id':owner,'ttl_sec':600}
  req=urllib.request.Request(base+'/workspaces',data=json.dumps(data).encode(),headers=headers)
  with urllib.request.urlopen(req,timeout=60) as r: result=json.load(r)
  assert result.get('versioned') is True
  result={'workspace_id':result['workspace_id'],'token':result['token'],'user_id':owner}
 else:
  data=p['fixture']; wid=data['workspace_id']
  method='DELETE' if mode=='delete' else 'POST'
  endpoint='' if mode=='delete' else '/history'
  req=urllib.request.Request(base+'/workspaces/'+wid+endpoint,
   data=json.dumps(data).encode(),headers=headers,method=method)
  with urllib.request.urlopen(req,timeout=30) as r: result=json.load(r)
  result={'deleted':True} if mode=='delete' else {
   'recovered':result.get('recovered') is True,
   'revision_present':isinstance(result.get('revision'),str) and bool(result['revision'])}
 print(json.dumps(result))
except BaseException:
 print(json.dumps({'status':'failed','stage':mode})); raise SystemExit(1)
"""


class ProbeFailure(Exception):
    """Only a closed stage code is safe for the operator report."""


def command(
    args: list[str], stage: str, *, data: str | None = None, timeout: int = 120
):
    try:
        result = subprocess.run(
            args,
            input=data,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ProbeFailure(stage) from None
    if result.returncode:
        raise ProbeFailure(stage)
    return result.stdout


def decoded(args: list[str], stage: str, **kwargs):
    try:
        return json.loads(command(args, stage, **kwargs))
    except (TypeError, ValueError):
        raise ProbeFailure(stage) from None


def health():
    code = (
        "import json,urllib.request; "
        "print(json.dumps(json.load(urllib.request.urlopen('http://localhost:8080/health'))))"
    )
    return decoded(["docker", "exec", WORKSPACE, "python3", "-c", code], "health")


def worker_nodes():
    nodes = []
    projection = (
        '{"running":{{json .State.Running}},"hostname":{{json .Config.Hostname}}}'
    )
    for container, prefix in WORKERS:
        state = decoded(
            ["docker", "inspect", "--format", projection, container],
            "workers_unavailable",
        )
        if not isinstance(state, dict) or state.get("running") is not True:
            raise ProbeFailure("workers_unavailable")
        hostname = state.get("hostname")
        if (
            not isinstance(hostname, str)
            or not hostname
            or len(hostname) > 253
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                for c in hostname
            )
        ):
            raise ProbeFailure("workers_unavailable")
        nodes.append(prefix + "@" + hostname)
    if len(set(nodes)) != len(WORKERS):
        raise ProbeFailure("workers_unavailable")
    return nodes


def idle():
    nodes = worker_nodes()
    report = decoded(
        ["docker", "exec", "-i", BACKEND, "python", "-c", _JOBS],
        "workers_unavailable",
        data=json.dumps(nodes),
        timeout=30,
    )
    categories = ("active", "reserved", "scheduled")
    if (
        not isinstance(report, dict)
        or report.get("complete") is not True
        or type(report.get("workers")) is not int
        or report["workers"] != len(WORKERS)
        or any(
            type(report.get(key)) is not int or report[key] < 0 for key in categories
        )
    ):
        raise ProbeFailure("workers_unavailable")
    counts = {key: report[key] for key in categories}
    if any(counts.get(key) != 0 for key in ("active", "reserved", "scheduled")):
        raise ProbeFailure("jobs_not_idle")
    current_health = health()
    documents = (
        current_health.get("documents") if isinstance(current_health, dict) else None
    )
    if not isinstance(documents, dict):
        raise ProbeFailure("documents_not_idle")
    # Successful reconciliations are a cumulative counter, not active work.
    cleaned = documents.get("compiler_cleanup")
    if type(cleaned) is not int or cleaned < 0:
        raise ProbeFailure("documents_not_idle")
    for key in ("active", "compiler_preparation_pending"):
        if type(documents.get(key)) is not int or documents[key] != 0:
            raise ProbeFailure("documents_not_idle")
    return counts


def configuration_matches():
    desired = decoded([*COMPOSE, "config", "--format", "json"], "compose_config")
    actual = decoded(["docker", "inspect", WORKSPACE], "inspect")[0]
    environment = dict(value.split("=", 1) for value in actual["Config"]["Env"])
    expected = desired["services"]["workspace"]["environment"]
    fields = (
        "WORKSPACE_OWNER_SECRET",
        "WORKSPACE_API_KEY",
        "WORKSPACE_COORDINATION_SECRET",
        "WORKSPACE_IMAGE",
        "WORKSPACE_TTL_SEC",
        "WORKSPACE_HARD_TTL_SEC",
    )
    if any(environment.get(key) != expected.get(key) for key in fields):
        raise ProbeFailure("configuration_changed")
    return actual


def owned(mode: str, fixture=None):
    # Send private fixture material through stdin, not argv, artifacts or logs.
    wire = json.dumps({"mode": mode, "fixture": fixture})
    wrapper = (
        "import sys; p=sys.stdin.read(); "
        + f"exec({('import io; sys.stdin=io.StringIO(p); ' + _HTTP)!r})"
    )
    return decoded(
        ["docker", "exec", "-i", BACKEND, "python", "-c", wrapper],
        "owned_" + mode,
        data=wire,
    )


def main():
    if os.getenv("S37_LIVE_WORKSPACE_RESTART") != "1":
        raise ProbeFailure("opt_in_required")
    before = configuration_matches()
    jobs = idle()
    initial = health()
    fixture = None
    cleaned = False
    try:
        fixture = owned("create")
        if set(fixture) != {"workspace_id", "user_id", "token"}:
            raise ProbeFailure("fixture_invalid")
        before_view = owned("history", fixture)
        if before_view != {"recovered": False, "revision_present": True}:
            raise ProbeFailure("fixture_not_fresh")
        command([*COMPOSE, "build", "workspace"], "build", timeout=600)
        expected_image = decoded(
            ["docker", "image", "inspect", "gpthub-dev-workspace"], "image_inspect"
        )[0]["Id"]
        configuration_matches()
        idle()
        command(
            [*COMPOSE, "up", "-d", "--no-deps", "--force-recreate", "workspace"],
            "recreate",
        )
        deadline = time.monotonic() + 90
        while True:
            try:
                current = health()
                if current.get("status") == "ok":
                    break
            except ProbeFailure:
                pass
            if time.monotonic() >= deadline:
                raise ProbeFailure("startup_timeout")
            time.sleep(1)
        after = decoded(["docker", "inspect", WORKSPACE], "inspect")[0]
        if after["Id"] == before["Id"] or after["Image"] != expected_image:
            raise ProbeFailure("runtime_not_recreated")
        restored = owned("history", fixture)
        if restored != {"recovered": True, "revision_present": True}:
            raise ProbeFailure("http_recovery_failed")
        if owned("validation") != {"invalid_request_redacted": True}:
            raise ProbeFailure("validation_reflected_input")
        if owned("delete", fixture) != {"deleted": True}:
            raise ProbeFailure("cleanup_failed")
        cleaned = True
        return {
            "status": "passed",
            "scoped_recreate": True,
            "built_image_running": True,
            "original_token_http_recovery": True,
            "invalid_request_redacted": True,
            "owned_fixture_deleted": True,
            "jobs_before": jobs,
            "documents_recovery_pending_before": initial["documents"][
                "recovery_pending"
            ],
            "documents_recovery_pending_after": current["documents"][
                "recovery_pending"
            ],
        }
    finally:
        if fixture and not cleaned:
            owned("delete", fixture)


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except ProbeFailure as failure:
        print(json.dumps({"status": "failed", "stage": str(failure)}))
        raise SystemExit(1) from None
