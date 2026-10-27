"""Host-side lifetime of isolated HTTP services; permanent dev stays unchanged."""

import json
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

WORKSPACE_SERVER = (
    "import sys;sys.path.insert(0,sys.argv[1]);import workspace_server;workspace_server.main()"
)
HEALTH = (
    "import urllib.request; "
    "assert urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=1).status==200"
)
CLEANUP = r"""
import asyncio, sys
from drivers.docker_cli import DockerCliDriver
from drivers.inventory import DockerInventory
async def main():
    driver = DockerCliDriver(inventory=DockerInventory(sys.argv[1]))
    for item in await driver.list_managed():
        await driver.destroy(item.ref)
asyncio.run(main())
"""


def docker(*args, timeout=45):
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        for line in result.stdout.splitlines():
            if line.startswith('{"stage":') or line.startswith('{"retained_database":'):
                print(line)
        raise RuntimeError("acceptance_docker_" + args[0] + "_failed")
    return result.stdout.strip()


def temporary(container):
    path = docker("exec", container, "mktemp", "-d", "/tmp/gpthub-harness-XXXXXXXX")
    assert re.fullmatch(r"/tmp/gpthub-harness-[A-Za-z0-9]{8}", path)
    return path


def remove_source(container, path):
    assert re.fullmatch(r"/tmp/gpthub-harness-[A-Za-z0-9]{8}", path)
    docker("exec", container, "python", "-c", "import shutil,sys;shutil.rmtree(sys.argv[1])", path)


def remove_broker(broker, scope):
    assert re.fullmatch(r"gpthub-harness-broker-[a-f0-9]{32}", broker)
    assert re.fullmatch(r"acceptance-http-[a-f0-9]{32}", scope)
    assert (
        docker(
            "inspect", broker, "--format", '{{index .Config.Labels "gpthub.harness.acceptance"}}'
        )
        == scope
    )
    docker("rm", "-f", broker)


def wait_workspace(process, workspace):
    deadline = time.monotonic() + 30
    while True:
        assert process.poll() is None, "acceptance_workspace_stopped"
        try:
            docker("exec", workspace, "python", "-c", HEALTH, timeout=3)
            return
        except (RuntimeError, subprocess.TimeoutExpired):
            # Таймаут наблюдения не означает остановку сервера. Проверяем тот же
            # процесс до исходного дедлайна, без перезапуска и нового исполнителя.
            if time.monotonic() >= deadline:
                raise RuntimeError("acceptance_workspace_not_ready") from None
            time.sleep(0.1)


def run_command_probe(
    *,
    existing=None,
    agents=False,
    scenario="hello",
    provider="gigachat",
    cleanup_terminal=False,
    worker=False,
    ack_fault="",
    worker_crash=False,
    crash_boundary="checkpoint",
    resume_tuning=False,
    agents_restart=False,
    restart_stop=False,
    restart_exhausted="",
    stop_before_dispatch=False,
    worker_stop=False,
    resume_cancel=False,
    retention=False,
    workspace_fault="",
    paid=False,
    paid_retire=False,
    paid_resume=False,
    question_resume=False,
    question_boundary="",
    invalid_arguments=False,
    verification_case="",
    paid_model="GigaChat-3-Lightning",
    local_model=False,
    review_questions=False,
):
    assert not review_questions or (
        agents
        and worker
        and scenario == "clarify"
        and existing is None
        and not question_boundary
        and not paid
        and not ack_fault
    )
    assert not local_model or (
        agents
        and not worker
        and not paid
        and existing is None
        and scenario == "hello"
        and provider == "local"
        and not ack_fault
        and not workspace_fault
    )
    assert paid_model in {"GigaChat-3-Lightning", "GigaChat-2-Max"}
    assert question_boundary in {
        "",
        "cancel",
        "expiry",
        "stop_child",
        "cost_decline",
        "cost_expiry",
        "cost_ack",
    }
    assert not question_boundary or (
        agents and worker and scenario == "clarify" and existing is None
    )
    assert not question_resume or (
        existing is not None
        and not agents
        and not worker
        and not paid
        and not paid_resume
        and not cleanup_terminal
        and scenario == "clarify"
    )
    assert verification_case in {
        "",
        "unittest_pass",
        "unittest_fail",
        "empty",
        "skipped",
        "pytest_missing",
        "pytest_pass",
        "pytest_fail",
        "pytest_empty",
        "pytest_skipped",
        "stdout_extra",
        "truncated",
    }
    assert not verification_case or (
        existing is None
        and not agents
        and not worker
        and not paid
        and not retention
        and not workspace_fault
        and not invalid_arguments
    )
    assert paid or paid_resume or paid_model == "GigaChat-3-Lightning"
    assert not paid_resume or (
        existing is not None
        and not paid
        and not paid_retire
        and not agents
        and not worker
        and not cleanup_terminal
        and not resume_cancel
    )
    assert not invalid_arguments or (not agents and existing is None and not worker and not paid)
    assert not paid_retire or (existing is not None and not paid and not agents and not worker)
    assert not paid or (
        agents
        and worker
        and existing is None
        and not workspace_fault
        and not ack_fault
        and not worker_crash
        and not worker_stop
        and scenario == "hello"
        and provider == "gigachat"
    )
    assert workspace_fault in {
        "",
        "dispatch_ack",
        "restart_complete",
        "restart_stop",
        "document_acks",
    }
    assert workspace_fault != "document_acks" or scenario == "pdf_review"
    assert not workspace_fault or (existing is None and not retention and not ack_fault)
    assert not workspace_fault.startswith("restart_") or (not worker and not agents)
    assert not retention or (not agents and existing is None and not worker)
    assert not resume_cancel or (existing is not None and not agents and not worker)
    assert not worker_stop or (worker and not worker_crash and not ack_fault and scenario == "stop")
    assert not worker_crash or (worker and not ack_fault)
    assert crash_boundary in {"checkpoint", "provider_receipt"}
    assert crash_boundary == "checkpoint" or worker_crash
    assert not resume_tuning or (worker_crash and crash_boundary == "provider_receipt")
    assert not restart_stop or agents_restart
    assert restart_exhausted in {"", "after_write", "before_dispatch"}
    assert not restart_exhausted or (agents_restart and not restart_stop)
    assert not stop_before_dispatch or (
        worker and not agents_restart and not worker_stop and not paid and not ack_fault
    )
    assert not agents_restart or (
        worker
        and not worker_crash
        and not ack_fault
        and not worker_stop
        and not paid
        and scenario == "hello"
        and existing is None
        and not workspace_fault
    )
    assert ack_fault in {
        "",
        "checkpoint",
        "file_receipt",
        "paid_receipt",
        "question_cost",
        "paid_receipt_unavailable",
        "stream_receipt_unavailable",
    }
    assert ack_fault != "question_cost" or question_boundary == "cost_ack"
    assert worker or not ack_fault
    assert not worker or (
        agents
        and existing is None
        and (provider == "gigachat" or scenario in {"read_change", "question_change"})
        and (
            scenario
            in {"hello", "clarify", "refine", "lesson_reuse", "read_change", "question_change"}
            or worker_stop
        )
    )
    assert not cleanup_terminal or (existing is not None and not agents)
    assert scenario in {
        "hello",
        "repair",
        "stop",
        "clarify",
        "refine",
        "lesson_reuse",
        "read_change",
        "question_change",
        "finish",
        "long",
        "pdf_review",
    }
    assert scenario != "pdf_review" or (
        agents
        and not worker
        and not existing
        and not paid
        and not ack_fault
        and workspace_fault in {"", "document_acks"}
    )
    assert scenario != "clarify" or ((worker or question_resume) and not paid and not worker_crash)
    assert agents or question_resume or scenario == "hello"
    assert provider in {"gigachat", "routerai", "openai"} or (local_model and provider == "local")
    assert agents or provider == "gigachat"
    root = Path(__file__).resolve().parents[4]
    workspace, backend = "gpthub-dev-workspace-1", "gpthub-dev-backend-1"
    scope = "acceptance-http-" + uuid4().hex
    ws_path, api_path = temporary(workspace), temporary(backend)
    if existing:
        # Reuse the actual inventory/journal; this path never creates another command.
        remove_source(workspace, ws_path)
        remove_source(backend, api_path)
        scope = existing["retained_scope"]
        ws_path, api_path = existing["workspace_source"], existing["backend_source"]
        assert re.fullmatch(r"acceptance-http-[a-f0-9]{32}", scope)
        for path in (ws_path, api_path):
            assert re.fullmatch(r"/tmp/gpthub-harness-[A-Za-z0-9]{8}", path)
    agent_process = None
    agent_path = existing.get("agents_source") if existing else None
    broker = None
    process, success = None, False
    try:
        if resume_cancel or (
            (cleanup_terminal or paid_retire or paid_resume or question_resume)
            and existing.get("broker")
        ):
            broker = existing["broker"]
            assert re.fullmatch(r"gpthub-harness-broker-[a-f0-9]{32}", broker)
            assert (
                docker(
                    "inspect",
                    broker,
                    "--format",
                    '{{index .Config.Labels "gpthub.harness.acceptance"}}',
                )
                == scope
            )
        if existing:
            docker(
                "cp",
                str(root / "backend/scripts/harness/live") + "/.",
                f"{backend}:{api_path}/scripts/harness/live",
            )
        else:
            docker("cp", str(root / "workspace/service"), f"{workspace}:{ws_path}/service")
            docker("cp", str(root / "backend/scripts"), f"{backend}:{api_path}/scripts")
        docker(
            "cp",
            str(Path(__file__).with_name("workspace_server.py")),
            f"{workspace}:{ws_path}/workspace_server.py",
        )
        process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                "-w",
                ws_path + "/service",
                "-e",
                "WORKSPACE_DOCKER_SCOPE=" + scope,
                "-e",
                "WORKSPACE_COORDINATOR_URL=http://backend:8002",
                "-e",
                "HARNESS_ACCEPTANCE_WORKSPACE_FAULT=" + workspace_fault,
                "-e",
                "WORKSPACE_IMAGE="
                + (
                    "gpthub-workspace-runtime:harness-pytest"
                    if verification_case.startswith("pytest_")
                    and verification_case != "pytest_missing"
                    else "gpthub-workspace-runtime:latest"
                ),
                workspace,
                "python",
                "-c",
                WORKSPACE_SERVER,
                ws_path,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_workspace(process, workspace)
        if agents or question_resume:
            if not question_resume:
                assert existing is None
                agent_path = temporary("gpthub-dev-agents-1")
                docker(
                    "cp", str(root / "agents/scripts"), f"gpthub-dev-agents-1:{agent_path}/scripts"
                )
            else:
                assert re.fullmatch(r"/tmp/gpthub-harness-[A-Za-z0-9]{8}", agent_path)
                docker(
                    "cp",
                    str(root / "agents/scripts") + "/.",
                    f"gpthub-dev-agents-1:{agent_path}/scripts",
                )
            agent_module = "local_server" if local_model else "paid_server" if paid else "server"
            agent_bootstrap = (
                "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
                f"runpy.run_module('scripts.harness_live.{agent_module}',run_name='__main__')"
            )
            agent_process = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-e",
                    "AGENTS__HARNESS_BACKEND_URL=http://backend:8002",
                    "-e",
                    "AGENTS__WORKSPACE_URL=http://workspace:8082",
                    "-e",
                    "AGENTS__HARNESS_REFINEMENT_ENABLED="
                    + ("true" if review_questions else "false"),
                    "-e",
                    "HARNESS_ACCEPTANCE_SCENARIO=" + scenario,
                    "-e",
                    "HARNESS_ACCEPTANCE_PROVIDER=" + provider,
                    "-e",
                    "HARNESS_ACCEPTANCE_PAID_MODEL=" + paid_model,
                    "-e",
                    "HARNESS_ACCEPTANCE_RESTART_EXHAUSTED=" + restart_exhausted,
                    "gpthub-dev-agents-1",
                    "python",
                    "-c",
                    agent_bootstrap,
                    agent_path,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if local_model:
                from scripts.harness.live.local_setup import initialize_local_process

                initialize_local_process(agent_process, root)
            deadline = time.monotonic() + 30
            while True:
                assert agent_process.poll() is None, "acceptance_agents_stopped"
                try:
                    docker(
                        "exec",
                        "gpthub-dev-agents-1",
                        "python",
                        "-c",
                        HEALTH.replace("8082", "8091"),
                        timeout=3,
                    )
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("acceptance_agents_not_ready") from None
                    time.sleep(0.1)
        if worker:
            broker = "gpthub-harness-broker-" + uuid4().hex
            image = docker("inspect", "gpthub-dev-redis-1", "--format", "{{.Config.Image}}")
            docker(
                "run",
                "-d",
                "--name",
                broker,
                "--network",
                "gpthub-dev_internal",
                "--label",
                "gpthub.harness.acceptance=" + scope,
                image,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
            )
            deadline = time.monotonic() + 15
            while True:
                try:
                    assert docker("exec", broker, "redis-cli", "ping") == "PONG"
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("acceptance_broker_not_ready") from None
                    time.sleep(0.1)
        module = (
            "documents.main"
            if scenario == "pdf_review"
            else "local_agent"
            if local_model
            else "stop_before_dispatch"
            if stop_before_dispatch
            else "question_boundary"
            if question_boundary
            else "question_resume"
            if question_resume
            else "verification_profiles"
            if verification_case
            else "invalid_arguments"
            if invalid_arguments
            else "paid_resume"
            if paid_resume
            else "paid_retire"
            if paid_retire
            else "paid"
            if paid
            else "retention"
            if retention
            else "workspace_restart"
            if workspace_fault.startswith("restart_")
            else "resume_cancel"
            if resume_cancel
            else "stop"
            if worker_stop
            else "crash"
            if worker_crash
            else "agents_restart"
            if agents_restart
            else "question"
            if scenario == "clarify"
            else "lesson_reuse"
            if scenario == "lesson_reuse"
            else "read_change"
            if scenario == "read_change"
            else "question_change"
            if scenario == "question_change"
            else "worker"
            if worker
            else "cleanup"
            if cleanup_terminal
            else "reconcile"
            if existing
            else "agent"
            if agents
            else "command"
        )
        bootstrap = (
            "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
            f"runpy.run_module('scripts.harness.live.{module}',run_name='__main__')"
        )
        arguments = (
            [existing["job_id"] if paid_retire or paid_resume else existing["database"]]
            if existing
            else [verification_case]
            if verification_case
            else []
        )
        broker_env = (
            [
                "-e",
                "CELERY__BROKER_URL=redis://" + broker + ":6379/0",
                "-e",
                "CELERY__RESULT_BACKEND=redis://" + broker + ":6379/1",
            ]
            if broker
            else []
        )
        raw = docker(
            "exec",
            *broker_env,
            "-e",
            "HARNESS_ACCEPTANCE_SCENARIO=" + scenario,
            "-e",
            "HARNESS_ACCEPTANCE_PROVIDER=" + provider,
            "-e",
            "HARNESS_ACCEPTANCE_LOST_ACK=" + ack_fault,
            "-e",
            "HARNESS_ACCEPTANCE_CRASH_BOUNDARY=" + crash_boundary,
            "-e",
            "HARNESS_ACCEPTANCE_RESUME_TUNING=" + ("true" if resume_tuning else "false"),
            "-e",
            "HARNESS_ACCEPTANCE_RESTART_STOP=" + ("true" if restart_stop else "false"),
            "-e",
            "HARNESS_ACCEPTANCE_RESTART_EXHAUSTED=" + restart_exhausted,
            "-e",
            "HARNESS_ACCEPTANCE_WORKSPACE_FAULT=" + workspace_fault,
            "-e",
            "HARNESS_ACCEPTANCE_PAID_MODEL=" + paid_model,
            "-e",
            "HUMAN_QUESTIONS__ENABLED="
            + ("true" if scenario in {"clarify", "question_change"} else "false"),
            "-e",
            "HARNESS_ACCEPTANCE_QUESTION_BOUNDARY=" + question_boundary,
            "-e",
            "HARNESS_ACCEPTANCE_REVIEW_QUESTIONS=" + ("true" if review_questions else "false"),
            backend,
            "python",
            "-c",
            bootstrap,
            api_path,
            *arguments,
            timeout=900
            if paid or local_model
            else 360
            if scenario == "long"
            else 300
            if worker or resume_cancel or paid_resume or question_resume
            else 180,
        )
        lines = [json.loads(line) for line in raw.splitlines() if line.startswith("{")]
        outcome = lines[-1]
        expected = (
            {
                "reconciled_stop": True,
                "command_repeated": False,
                "fixture_data_removed": True,
            }
            if existing
            else {
                "command_verified": True,
                "http_replay_stable": True,
                "agents_worker_covered": False,
                "fixture_data_removed": True,
            }
        )
        if verification_case:
            assert outcome == {
                "verification_profile_verified": verification_case,
                "replay_unchanged": True,
                "fixture_data_removed": True,
            }
        elif invalid_arguments:
            assert outcome == {
                "invalid_arguments_reconciled": True,
                "corrected_operation_verified": True,
                "fixture_data_removed": True,
            }
        elif paid_resume:
            assert outcome["paid_resume_verified"] and not outcome["new_paid_calls"]
            assert outcome["model"] == paid_model and outcome["charges"] == 1
            assert outcome["redelivery_unchanged"] and outcome["restart_redelivery_unchanged"]
            assert outcome["test_runtime_removed"] and outcome["journal_and_snapshots_preserved"]
        elif paid_retire:
            assert outcome == {
                "paid_terminal_retired": True,
                "new_paid_calls": False,
                "journal_and_snapshots_preserved": True,
            }
        elif paid:
            assert outcome["paid_harness_verified"] and outcome["charges"] == 1
            assert outcome["model"] == paid_model
            assert outcome["test_runtime_removed"] and outcome["journal_and_snapshots_preserved"]
        elif workspace_fault.startswith("restart_"):
            assert outcome == {
                "workspace_restart_verified": True,
                "stop": workspace_fault == "restart_stop",
                "output_verification_blocked": True,
                "command_repeated": False,
                "fixture_data_removed": True,
            }
        elif retention:
            assert outcome == {"retention_trigger_verified": True, "fixture_data_removed": True}
        elif resume_cancel:
            assert outcome == {
                "cancelled_resume_verified": True,
                "new_effects": False,
                "charges": 1,
                "fixture_data_removed": True,
            }
        elif stop_before_dispatch:
            assert outcome == {
                "stop_before_dispatch_verified": True,
                "model_calls": 0,
                "project_effects": 0,
                "spent_credits": 0,
                "fixture_data_removed": True,
            }
        elif worker_stop:
            assert outcome == {
                "worker_stop_verified": True,
                "cleanup_confirmed": True,
                "mutation_gate_verified": True,
                "late_dispatch_denied": True,
                "fixture_data_removed": True,
            }
        elif worker_crash:
            assert outcome == {
                "worker_crash_recovered": True,
                "write_effects": 1,
                "command_effects": 1,
                "charges": 1,
                "old_attempt_fenced": True,
                "fixture_data_removed": True,
                **({"completed_slot_reused": True} if resume_tuning else {}),
            }
        elif restart_stop:
            assert outcome == {
                "agents_restart_stopped": True,
                "write_effects": 1,
                "command_effects": 0,
                "charges": 1,
                "fixture_data_removed": True,
            }
        elif restart_exhausted:
            assert outcome == {
                "agents_restart_exhausted": True,
                "write_effects": 0 if restart_exhausted == "before_dispatch" else 1,
                "command_effects": 0,
                "charges": 0 if restart_exhausted == "before_dispatch" else 1,
                "fixture_data_removed": True,
            }
        elif agents_restart:
            assert outcome == {
                "agents_restart_recovered": True,
                "write_effects": 1,
                "command_effects": 1,
                "charges": 1,
                "old_attempt_fenced": True,
                "fixture_data_removed": True,
            }
        elif question_boundary:
            assert outcome["question_boundary_verified"] == question_boundary
            assert outcome["fixture_data_removed"] and outcome["replay_unchanged"]
            assert outcome["commands"] == int(question_boundary == "cost_ack")
        elif question_resume:
            assert outcome["question_harness_verified"] and outcome["resumed_existing_question"]
            assert outcome["command_effects"] == 1 and outcome["usage_charges"] == 2
            assert outcome["fixture_data_removed"] and outcome["replay_and_restart_unchanged"]
        elif scenario == "clarify":
            assert outcome == {
                "question_harness_verified": True,
                "outbox_worker_resumed": True,
                "replay_and_restart_unchanged": True,
                "command_effects": 1,
                "usage_charges": 2,
                "fixture_data_removed": True,
                **({"reviewed_question_resume_verified": True} if review_questions else {}),
            }
        elif scenario == "lesson_reuse":
            assert outcome == {
                "lesson_reuse_verified": True,
                "skipped_new_refinement": True,
                "mutations": 0,
                "commands": 0,
                "charges": 2,
                "replay_unchanged": True,
                "restart_replay_unchanged": True,
                "fixture_data_removed": True,
            }
        elif scenario == "read_change":
            assert outcome == {
                "stale_read_blocked": True,
                "user_edit_preserved": True,
                "agent_mutations": 0,
                "commands": 0,
                "charges": 1,
                "replay_unchanged": True,
                "restart_replay_unchanged": True,
                "fixture_data_removed": True,
            }
        elif scenario == "question_change":
            assert outcome == {
                "parked_read_invalidated": True,
                "child_reread_verified": True,
                "same_task_criteria_counters": True,
                "user_edit_preserved": True,
                "charges": 2,
                "mutations": 0,
                "commands": 0,
                "replay_and_restart_unchanged": True,
                "fixture_data_removed": True,
            }
        elif worker:
            assert outcome == {
                "worker_harness_verified": True,
                "redelivery_unchanged": True,
                "restart_redelivery_unchanged": True,
                "lost_ack_reconciled": ack_fault,
                "charges": 1,
                "commands": 1,
                "fixture_data_removed": True,
                **({"instruction_refinement_verified": True} if scenario == "refine" else {}),
            }
        elif cleanup_terminal:
            assert outcome == {"terminal_fixture_removed": True, "fixture_data_removed": True}
        elif local_model:
            assert outcome["local_model_ide_verified"] and outcome["fixture_data_removed"]
            assert not outcome["worker_covered"] and 0 < outcome["rounds"] <= 16
        elif scenario == "pdf_review":
            assert outcome["structural_review_verified"] and outcome["actual_pdf_verified"]
            assert outcome["build_replay_unchanged"] and outcome["fixture_data_removed"]
            assert not outcome["automatic_apply"] and not outcome["worker_covered"]
        elif agents:
            assert outcome["agents_harness_verified"] and outcome["rounds"] >= 5
            assert outcome["fixture_data_removed"] and not outcome["worker_covered"]
        else:
            assert outcome == expected
        success = True
        return outcome
    finally:
        if agent_process and agent_process.stdin:
            agent_process.stdin.close()
            agent_process.wait(timeout=20)
        if process and process.stdin:
            process.stdin.close()
            process.wait(timeout=20)
        if success:
            docker("exec", "-w", ws_path + "/service", workspace, "python", "-c", CLEANUP, scope)
            remove_source(workspace, ws_path)
            remove_source(backend, api_path)
            if agent_path:
                remove_source("gpthub-dev-agents-1", agent_path)
            if broker:
                remove_broker(broker, scope)
        else:
            # Preserve process evidence/journal after uncertainty, not a blind retry.
            print(
                json.dumps(
                    {
                        "retained_scope": scope,
                        "workspace_source": ws_path,
                        "backend_source": api_path,
                        "agents_source": agent_path,
                        "broker": broker,
                    }
                )
            )
