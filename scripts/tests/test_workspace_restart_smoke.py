"""Safety checks for the opt-in scoped development runtime acceptance."""

import ast
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).parents[1] / "smoke_workspace_restart.py"
spec = importlib.util.spec_from_file_location("workspace_restart_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_remote_http_probe_is_valid_python():
    ast.parse(smoke._HTTP)


def test_no_opt_in_means_no_commands(monkeypatch):
    monkeypatch.delenv("S37_LIVE_WORKSPACE_RESTART", raising=False)
    command = Mock()
    monkeypatch.setattr(smoke, "command", command)
    with pytest.raises(smoke.ProbeFailure, match="opt_in_required"):
        smoke.main()
    command.assert_not_called()


@pytest.mark.parametrize("counts", [{"active": None}, {"active": 1}])
def test_unknown_or_active_jobs_block_restart(monkeypatch, counts):
    counts = {"reserved": 0, "scheduled": 0, **counts}
    monkeypatch.setattr(smoke, "decoded", lambda *_, **kwargs: counts)
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(smoke, "health", lambda: {"documents": {}})
    with pytest.raises(smoke.ProbeFailure, match="workers_unavailable"):
        smoke.idle()


def test_running_compiler_blocks_restart(monkeypatch):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda *_, **kwargs: dict(
            active=0, reserved=0, scheduled=0, complete=True, workers=2
        ),
    )
    monkeypatch.setattr(smoke, "health", lambda: {"documents": {"active": 1}})
    with pytest.raises(smoke.ProbeFailure, match="documents_not_idle"):
        smoke.idle()


@pytest.mark.parametrize("cleaned", [1, 7])
def test_completed_cleanup_counter_does_not_block_idle_runtime(monkeypatch, cleaned):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda *_, **kwargs: dict(
            active=0,
            reserved=0,
            scheduled=0,
            complete=True,
            workers=2,
        ),
    )
    monkeypatch.setattr(
        smoke,
        "health",
        lambda: {
            "documents": {
                "active": 0,
                "compiler_cleanup": cleaned,
                "compiler_preparation_pending": 0,
            }
        },
    )
    assert smoke.idle() == {"active": 0, "reserved": 0, "scheduled": 0}


@pytest.mark.parametrize("cleaned", [None, True, -1, "1"])
def test_invalid_cleanup_counter_is_not_idle_evidence(monkeypatch, cleaned):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda *_, **kwargs: dict(
            active=0,
            reserved=0,
            scheduled=0,
            complete=True,
            workers=2,
        ),
    )
    monkeypatch.setattr(
        smoke,
        "health",
        lambda: {
            "documents": {
                "active": 0,
                "compiler_cleanup": cleaned,
                "compiler_preparation_pending": 0,
            }
        },
    )
    with pytest.raises(smoke.ProbeFailure, match="documents_not_idle"):
        smoke.idle()


@pytest.mark.parametrize(
    "report",
    [
        dict(active=0, reserved=0, scheduled=0),
        dict(active=0, reserved=0, scheduled=0, complete=False, workers=2),
        dict(active=0, reserved=0, scheduled=0, complete=True, workers=1),
        dict(active=0, reserved=0, scheduled=None, complete=True, workers=2),
        dict(active=False, reserved=0, scheduled=0, complete=True, workers=2),
        [],
    ],
)
def test_partial_or_malformed_worker_report_blocks_restart(monkeypatch, report):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(smoke, "decoded", lambda *_, **kwargs: report)
    healthy = Mock()
    monkeypatch.setattr(smoke, "health", healthy)
    with pytest.raises(smoke.ProbeFailure, match="workers_unavailable"):
        smoke.idle()
    healthy.assert_not_called()


def test_complete_busy_workers_block_restart(monkeypatch):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda *_, **kwargs: dict(
            active=1, reserved=0, scheduled=0, complete=True, workers=2
        ),
    )
    with pytest.raises(smoke.ProbeFailure, match="jobs_not_idle"):
        smoke.idle()


@pytest.mark.parametrize(
    "bad_reply",
    [
        None,
        {},
        {"agent-worker@a": []},
        {"maintenance-worker@b": []},
        {"agent-worker@a": [], "maintenance-worker@b": {}},
        {"agent-worker@a": [], "unexpected-private-node": []},
    ],
)
@pytest.mark.parametrize("category", ["active", "reserved", "scheduled"])
def test_remote_probe_requires_every_worker_for_every_category(
    monkeypatch, capsys, bad_reply, category
):
    nodes = ["agent-worker@a", "maintenance-worker@b"]
    replies = {
        key: {node: [] for node in nodes} for key in ("active", "reserved", "scheduled")
    }
    replies[category] = bad_reply
    report = run_remote_probe(monkeypatch, capsys, nodes, replies)
    assert report["complete"] is False
    assert report[category] is None
    assert "unexpected-private-node" not in json.dumps(report)


def run_remote_probe(monkeypatch, capsys, nodes, replies):
    module = ModuleType("service.infrastructure.messaging.celery_app")
    inspector = SimpleNamespace(
        **{key: Mock(return_value=value) for key, value in replies.items()}
    )
    inspect = Mock(return_value=inspector)
    module.celery_app = SimpleNamespace(control=SimpleNamespace(inspect=inspect))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(nodes)))
    exec(compile(smoke._JOBS, "private_worker_probe", "exec"), {})
    inspect.assert_called_once_with(destination=nodes, timeout=5)
    return json.loads(capsys.readouterr().out)


def test_remote_probe_emits_counts_not_task_material(monkeypatch, capsys):
    nodes = ["agent-worker@a", "maintenance-worker@b"]
    replies = {
        key: {node: [] for node in nodes} for key in ("active", "reserved", "scheduled")
    }
    replies["reserved"][nodes[1]] = [{"args": "private-request-marker"}]
    report = run_remote_probe(monkeypatch, capsys, nodes, replies)
    assert report == dict(complete=True, workers=2, active=0, reserved=1, scheduled=0)
    assert "private-request-marker" not in json.dumps(report)


@pytest.mark.parametrize(
    "state",
    [
        None,
        [],
        {},
        {"running": False},
        {"running": True, "hostname": "private/host"},
        {"running": True, "hostname": ""},
        {"running": True, "hostname": 1},
    ],
)
def test_worker_topology_failures_are_bounded(monkeypatch, state):
    monkeypatch.setattr(smoke, "decoded", lambda *_: state)
    with pytest.raises(smoke.ProbeFailure, match="^workers_unavailable$"):
        smoke.worker_nodes()


def test_topology_uses_only_running_hostname_projection(monkeypatch):
    decoded = Mock(
        side_effect=[dict(running=True, hostname="a"), dict(running=True, hostname="b")]
    )
    monkeypatch.setattr(smoke, "decoded", decoded)
    assert smoke.worker_nodes() == ["agent-worker@a", "maintenance-worker@b"]
    for call in decoded.call_args_list:
        args = call.args[0]
        assert args[:3] == ["docker", "inspect", "--format"]
        assert "Env" not in args[3] and "Running" in args[3] and "Hostname" in args[3]


def test_complete_idle_snapshot_is_read_only(monkeypatch):
    monkeypatch.setattr(
        smoke, "worker_nodes", lambda: ["agent-worker@a", "maintenance-worker@b"]
    )
    remote = Mock(
        return_value=dict(complete=True, workers=2, active=0, reserved=0, scheduled=0)
    )
    monkeypatch.setattr(smoke, "decoded", remote)
    monkeypatch.setattr(
        smoke,
        "health",
        lambda: {
            "documents": dict(
                active=0, compiler_cleanup=0, compiler_preparation_pending=0
            )
        },
    )
    assert smoke.idle() == dict(active=0, reserved=0, scheduled=0)
    assert remote.call_args.args[0][:4] == ["docker", "exec", "-i", smoke.BACKEND]


def test_secret_configuration_change_blocks_recreate(monkeypatch):
    def decoded(args, stage):
        if stage == "compose_config":
            return {
                "services": {
                    "workspace": {
                        "environment": {
                            "WORKSPACE_OWNER_SECRET": "replacement",
                        }
                    }
                }
            }
        return [{"Config": {"Env": ["WORKSPACE_OWNER_SECRET=existing"]}}]

    monkeypatch.setattr(smoke, "decoded", decoded)
    with pytest.raises(smoke.ProbeFailure, match="configuration_changed") as caught:
        smoke.configuration_matches()
    assert "replacement" not in str(caught.value)
    assert "existing" not in str(caught.value)


def test_recreate_is_scoped_and_preserves_original_capability(monkeypatch):
    monkeypatch.setenv("S37_LIVE_WORKSPACE_RESTART", "1")
    monkeypatch.setattr(smoke, "configuration_matches", lambda: {"Id": "old"})
    monkeypatch.setattr(smoke, "idle", lambda: dict(active=0, reserved=0, scheduled=0))
    monkeypatch.setattr(
        smoke,
        "health",
        lambda: {
            "status": "ok",
            "documents": {"recovery_pending": 1},
        },
    )
    monkeypatch.setattr(
        smoke,
        "decoded",
        lambda args, stage: [
            {"Id": "new", "Image": "new-image"}
            if stage == "inspect"
            else {"Id": "new-image"}
        ],
    )
    commands = Mock(return_value="")
    monkeypatch.setattr(smoke, "command", commands)
    fixture = {
        "workspace_id": "owned",
        "user_id": "owner",
        "token": "fixture-capability",
    }
    calls = []

    def owned(mode, payload=None):
        calls.append((mode, payload))
        if mode == "create":
            return fixture
        if mode == "validation":
            assert payload is None
            return {"invalid_request_redacted": True}
        assert payload is fixture
        if mode == "delete":
            return {"deleted": True}
        return {"revision_present": True, "recovered": len(calls) > 2}

    monkeypatch.setattr(smoke, "owned", owned)
    report = smoke.main()
    assert report["original_token_http_recovery"] is True
    assert report["owned_fixture_deleted"] is True
    assert [call[0] for call in calls] == [
        "create",
        "history",
        "history",
        "validation",
        "delete",
    ]
    argv = [call.args[0] for call in commands.call_args_list]
    assert argv == [
        [*smoke.COMPOSE, "build", "workspace"],
        [*smoke.COMPOSE, "up", "-d", "--no-deps", "--force-recreate", "workspace"],
    ]
    assert fixture["token"] not in str(report)
