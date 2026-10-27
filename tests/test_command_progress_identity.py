"""Исправление одного рецепта не зависит от необязательных полей wire-запроса."""

import json

import pytest

from service.domain.execution.progress import TaskProgress
from service.domain.runners.tool_runtime import ToolCallOutcome

BASE = {
    "profile": "python_script",
    "target": "hello.py",
    "criterion_id": "verify_project",
    "expected_stdout": "hello world\n",
    "timeout_sec": 10,
    "command": None,
}


def observe(progress, arguments, status):
    progress.observe(
        {"name": "ide_run_command", "arguments": json.dumps(arguments)},
        ToolCallOutcome("bounded diagnostic", status, 0),
        revision="r1" if status == "failed" else "r2",
    )


@pytest.mark.parametrize("change", ["timeout", "omitted_null", "both", "invalid_command"])
def test_verified_same_recipe_clears_previous_failure_with_different_wire_defaults(change):
    progress = TaskProgress(active=True)
    first, corrected = dict(BASE), dict(BASE)
    if change in {"timeout", "both"}:
        corrected["timeout_sec"] = 30
    if change in {"omitted_null", "both"}:
        corrected.pop("command")
    if change == "invalid_command":
        first["command"] = "python hello.py"
    observe(progress, first, "failed")
    assert progress.result(cancelled=False, unconfirmed=False)["blocker"] == "tool_failed"
    observe(progress, corrected, "succeeded")
    assert progress.result(cancelled=False, unconfirmed=False) is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("target", "other.py"),
        ("criterion_id", "other_check"),
        ("profile", "unittest"),
        ("expected_stdout", "other output"),
    ],
)
def test_different_recipe_or_criterion_never_clears_the_original_failure(key, value):
    progress = TaskProgress(active=True)
    observe(progress, BASE, "failed")
    observe(progress, {**BASE, key: value}, "succeeded")
    assert progress.result(cancelled=False, unconfirmed=False)["blocker"] == "tool_failed"
