"""Обязательный формат не включает инструменты в обычном чате и не снимает Stop."""

from types import SimpleNamespace as NS

import pytest

from service.domain.runners.harness.tool_choice import harness_tool_choice


def state():
    return NS(
        tool_choice=None,
        openai_tools=[{"type": "function"}],
        provider_session=NS(pinned_provider="local"),
        execution=NS(
            harness=NS(failure=None),
            task_state=NS(contract=NS(kind="change"), cancelled=False, rounds=0),
            cancelled=False,
            workspace=NS(ide_unconfirmed=False),
            question=NS(prompt=None),
            resources=NS(workspace_ref={"ide_context": {}}),
            completion_verifier=NS(evaluate=lambda _: {"unchecked": ["file"]}),
        ),
    )


def test_local_unverified_change_uses_existing_tools_without_mutating_state():
    current = state()
    assert harness_tool_choice(current) == "required"
    assert current.tool_choice is None and len(current.openai_tools) == 1
    current.execution.completion_verifier.evaluate = lambda _: {"unchecked": []}
    assert harness_tool_choice(current) is None


def test_initial_tree_read_does_not_reset_after_saved_tool_round():
    current = state()
    current.openai_tools = [
        {"function": {"name": "ide_list_files"}},
        {"function": {"name": "ide_write_file"}},
    ]
    assert harness_tool_choice(current) == {
        "type": "function",
        "function": {"name": "ide_list_files"},
    }
    assert len(current.openai_tools) == 2
    current.execution.task_state.rounds = 1
    assert harness_tool_choice(current) == "required"


@pytest.mark.parametrize("choice", ["none", "auto", {"type": "function"}])
def test_explicit_choice_is_preserved(choice):
    current = state()
    current.tool_choice = choice
    assert harness_tool_choice(current) is choice


@pytest.mark.parametrize(
    "fault",
    [
        "chat",
        "analysis",
        "cloud",
        "no_tools",
        "stop",
        "task_stop",
        "unknown",
        "write_unknown",
        "question",
        "no_ide",
    ],
)
def test_no_forcing_outside_confirmed_local_ide_task(fault):
    current = state()
    execution = current.execution
    if fault == "chat":
        execution.harness = None
        execution.task_state = None
    elif fault == "analysis":
        execution.task_state.contract.kind = "analysis"
    elif fault == "cloud":
        current.provider_session.pinned_provider = "gigachat"
    elif fault == "no_tools":
        current.openai_tools = []
    elif fault == "stop":
        execution.cancelled = True
    elif fault == "task_stop":
        execution.task_state.cancelled = True
    elif fault == "unknown":
        execution.harness.failure = "operation_unknown"
    elif fault == "write_unknown":
        execution.workspace.ide_unconfirmed = True
    elif fault == "question":
        execution.question.prompt = "Нужно решение пользователя"
    else:
        execution.resources.workspace_ref = None
    assert harness_tool_choice(current) is None
