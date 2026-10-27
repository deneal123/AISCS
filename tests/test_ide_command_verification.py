"""Verification is recipe/version-bound; process exit alone is not task success."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.domain.ide.console import CommandResult
from service.services.chat.domain.ide.verification import verify
from service.services.chat.persistence.harness.commands import (
    completion,
    invalidation,
    write_versions,
)
from service.shared.harness_protocol import EffectResult
from service.shared.task_contract import CompletionVerifier
from tests.test_ide_harness_commands import result, running
from tests.test_task_contract import evidence, state


@pytest.mark.parametrize(
    "changes,status,reason",
    [
        ({}, "passed", ""),
        ({"stdout": "wrong"}, "failed", "unexpected_output"),
        ({"exit_code": 1}, "failed", "verification_failed"),
        ({"exit_code": 127}, "blocked", "runtime_unavailable"),
        ({"timed_out": True}, "failed", "command_timeout"),
        ({"truncated": True}, "blocked", "output_unavailable"),
    ],
)
def test_python_requires_actual_expected_output(changes, status, reason):
    spec = CommandSpec(profile="python_script", target="src/hello.py", expected_stdout="hello")
    actual = verify(spec, CommandResult.model_validate(result(**changes)), None)
    assert actual["status"] == status and actual["reason"] == reason


@pytest.mark.parametrize(
    "stdout,expected,status",
    [
        ("hello\n", "hello\n", "passed"),
        ("hello\r\n", "hello\n", "passed"),
        ("hello\n\n", "hello\n", "failed"),
        ("hello", "hello\n", "failed"),
        ("hello\n", "hello", "passed"),
        ("hello\n\n", "hello", "failed"),
        ("\n", "", "failed"),
    ],
)
def test_expected_newline_cannot_be_forged_by_stripping_arbitrary_blank_lines(
    stdout, expected, status
):
    spec = CommandSpec(profile="python_script", target="a.py", expected_stdout=expected)
    actual = verify(spec, CommandResult.model_validate(result(stdout=stdout)), None)
    assert actual["status"] == status


def test_successful_arbitrary_shell_and_script_without_expectation_do_not_verify():
    actual = CommandResult.model_validate(result())
    assert (
        verify(CommandSpec(profile="shell", command="true"), actual, None)["status"]
        == "not_requested"
    )
    assert (
        verify(CommandSpec(profile="python_script", target="a.py"), actual, None)["status"]
        == "blocked"
    )


@pytest.mark.parametrize("profile", ["unittest", "pytest"])
@pytest.mark.parametrize(
    "metrics,status",
    [
        (None, "blocked"),
        ({"executed": 0, "skipped": 0, "failed": 0}, "blocked"),
        ({"executed": 0, "skipped": 5, "failed": 0}, "blocked"),
        ({"executed": 1, "skipped": 0, "failed": 0}, "passed"),
        ({"executed": True, "skipped": 0, "failed": 0}, "blocked"),
        ({"executed": 1, "skipped": 0, "failed": 1}, "failed"),
    ],
)
def test_tests_require_nonempty_framework_result_not_fake_stdout(profile, metrics, status):
    if metrics is not None:
        metrics = {"version": 1, "profile": profile, **metrics}
    spec = CommandSpec(profile=profile, target="tests")
    actual = CommandResult.model_validate(result(stdout="100 tests passed"))
    assert verify(spec, actual, metrics)["status"] == status


@pytest.mark.parametrize(
    "profile,metrics,status,reason",
    [
        ("pytest", {"executed": 0, "skipped": 0, "failed": 0}, "blocked", "empty_test_suite"),
        ("pytest", None, "blocked", "verification_unavailable"),
        ("pytest", {"executed": 1, "skipped": 0, "failed": 0}, "failed", "verification_failed"),
        ("unittest", {"executed": 0, "skipped": 0, "failed": 0}, "failed", "verification_failed"),
    ],
)
def test_pytest_no_tests_exit_is_not_a_failed_project_or_success(profile, metrics, status, reason):
    if metrics is not None:
        metrics = {"version": 1, "profile": profile, **metrics}
    actual = CommandResult.model_validate(result(exit_code=5))
    spec = CommandSpec(profile=profile, target="tests")
    observed = verify(spec, actual, metrics)
    assert (observed["status"], observed["reason"]) == (status, reason)


@pytest.mark.asyncio
async def test_write_invalidates_previously_successful_command_check(monkeypatch):
    written = evidence()
    current = state(evidence=[written, evidence("test")])
    assert CompletionVerifier.evaluate(current)["status"] == "completed"
    receipt = EffectResult(
        operation_id=written.operation_id,
        status="succeeded",
        text="written",
        evidence=[written],
        charged=True,
    )
    monkeypatch.setattr(
        write_versions.effects,
        "read",
        AsyncMock(
            return_value={
                "intent": {"action": "write"},
                "receipt": None,
            }
        ),
    )
    monkeypatch.setattr(write_versions.effects, "record", AsyncMock())
    saved = AsyncMock()
    monkeypatch.setattr(write_versions, "save_checkpoint", saved)
    db = SimpleNamespace(execute=AsyncMock())
    await write_versions.accept_effect(
        db,
        {"task_id": UUID(current.contract.task_id)},
        receipt,
        SimpleNamespace(state=current, admission=SimpleNamespace(surface="ide"), continuation=None),
    )
    updated = saved.await_args.kwargs["state"]
    check = CompletionVerifier.evaluate(updated)
    assert updated.source_revision == "write:" + written.operation_id
    assert check["status"] != "completed" and check["unchecked"] == ["test"]


@pytest.mark.asyncio
async def test_successful_check_refreshes_only_unchanged_confirmed_target(monkeypatch):
    current = state(evidence=[evidence()])
    command = running().advance(
        state="completed",
        final_revision="tree2",
        result=result(),
        output_complete=True,
        cleanup_confirmed=True,
        spec={"profile": "python_script", "target": "src/hello_world.py", "criterion_id": "test"},
        verification={"status": "passed", "recipe_digest": "a" * 64},
    )
    monkeypatch.setattr(
        completion,
        "snapshot",
        AsyncMock(return_value=SimpleNamespace(state=current, continuation=None)),
    )
    monkeypatch.setattr(
        completion.effects, "read", AsyncMock(return_value={"status": "dispatched"})
    )
    saved = AsyncMock()
    monkeypatch.setattr(completion, "save_checkpoint", saved)
    db = SimpleNamespace(execute=AsyncMock())
    await completion.complete(
        db, {"task_id": UUID(current.contract.task_id)}, command, {"src/hello_world.py": "a" * 64}
    )
    assert CompletionVerifier.evaluate(saved.await_args.kwargs["state"])["status"] == "completed"
    # Reading another file or observing changed bytes cannot confirm the requested target.
    await completion.complete(
        db, {"task_id": UUID(current.contract.task_id)}, command, {"src/other.py": "a" * 64}
    )
    assert CompletionVerifier.evaluate(saved.await_args.kwargs["state"])["unchecked"] == ["source"]


@pytest.mark.asyncio
async def test_external_ui_write_invalidates_evidence_before_workspace_dispatch(monkeypatch):
    current = state(evidence=[evidence(), evidence("test")])
    assert CompletionVerifier.evaluate(current)["status"] == "completed"
    row = {"task_id": UUID(current.contract.task_id)}
    queried = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [row]))
    db = SimpleNamespace(execute=AsyncMock(return_value=queried), commit=AsyncMock())

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(
        invalidation,
        "snapshot",
        AsyncMock(return_value=SimpleNamespace(state=current, continuation=None)),
    )
    saved = AsyncMock()
    monkeypatch.setattr(invalidation, "save_checkpoint", saved)
    await invalidation.invalidate_external_write(
        SimpleNamespace(get_session_context=session), "workspace"
    )
    changed = saved.await_args.kwargs["state"]
    assert changed.source_revision.startswith("external:")
    assert CompletionVerifier.evaluate(changed)["status"] != "completed"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("verification", ["failed", "blocked"])
async def test_latest_failed_check_replaces_older_pass_even_at_same_revision(
    monkeypatch, verification
):
    current = state(evidence=[evidence(), evidence("test")])
    command = running().advance(
        state="failed",
        final_revision="r1",
        result=result(exit_code=1),
        output_complete=True,
        cleanup_confirmed=True,
        failure_reason="verification_failed",
        spec={"profile": "python_script", "target": "src/hello_world.py", "criterion_id": "test"},
        verification={"status": verification, "recipe_digest": "b" * 64},
    )
    monkeypatch.setattr(
        completion,
        "snapshot",
        AsyncMock(return_value=SimpleNamespace(state=current, continuation=None)),
    )
    monkeypatch.setattr(
        completion.effects, "read", AsyncMock(return_value={"status": "dispatched"})
    )
    saved = AsyncMock()
    monkeypatch.setattr(completion, "save_checkpoint", saved)
    db = SimpleNamespace(execute=AsyncMock())
    await completion.complete(db, {"task_id": UUID(current.contract.task_id)}, command, {})
    actual = CompletionVerifier.evaluate(saved.await_args.kwargs["state"])
    assert actual["status"] != "completed" and actual["unchecked"] == ["test"]
    assert db.execute.await_args.args[1]["status"] == "failed"
