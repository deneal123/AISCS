"""Наличие model-double не подменяет доказательство исправления ядром."""

import pytest

from scripts.harness_live.model_transport import ScriptedProvider
from scripts.harness_live.verification_repair import PREMATURE
from tests.test_harness_live_refinement_transport import send


@pytest.mark.parametrize("name", ["gigachat", "routerai", "openai"])
@pytest.mark.parametrize("guidance", [False, True])
@pytest.mark.parametrize("completed_repairs", range(4))
def test_double_only_repairs_after_core_feedback_and_tool_disclosure(
    monkeypatch, name, guidance, completed_repairs
):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_SCENARIO", "repair")
    monkeypatch.setenv("HARNESS_ACCEPTANCE_PROVIDER", name)
    provider = ScriptedProvider()
    completed = ["ide_list_files", "ide_write_file", "ide_read_file", "ide_run_command"]
    repairs = ["ide_read_file", "ide_edit_file", "ide_read_file", "ide_run_command"]
    completed.extend(repairs[:completed_repairs])
    expected_tool = repairs[completed_repairs]
    if name == "gigachat":
        messages = [{"role": "function", "name": tool, "content": "{}"} for tool in completed]
    else:
        messages = []
        for index, tool in enumerate(completed):
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "tool_calls": [{"id": str(index), "function": {"name": tool}}],
                    },
                    {"role": "tool", "tool_call_id": str(index), "content": "{}"},
                ]
            )
    if guidance:
        messages.append({"role": "user", "content": "[harness:verification-repair:synthetic]"})
    names = [expected_tool] if guidance else [expected_tool, "ide_finish_task"]
    response = send(provider, names, messages)
    assert provider.tool_names == [expected_tool if guidance else "ide_finish_task"]
    assert (PREMATURE in str(response)) is not guidance
