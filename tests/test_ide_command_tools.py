"""Tool wiring observes the same operation; it cannot mint command evidence."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    compile_toolset,
)
from service.domain.execution.progress import TaskProgress
from service.domain.runners.support import _tools_to_openai
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.tools.ide import commands, observation
from service.shared.harness_protocol import HarnessFailure


def setup(monkeypatch, *, prepared="prepared"):
    state = SimpleNamespace(source_revision="current")
    execution = SimpleNamespace(
        task_state=state,
        cancelled=False,
        workspace=SimpleNamespace(ide_reads={"old.py": "digest"}, ide_trees={}, observe=Mock()),
    )
    client = SimpleNamespace(
        failure="",
        task_id=str(uuid4()),
        current=SimpleNamespace(state=state, continuation=SimpleNamespace(next_step=4)),
        exchange=AsyncMock(
            side_effect=[
                {"operation": {"status": prepared}},
                {"operation": {"dispatch_allowed": True}},
            ]
        ),
        command=AsyncMock(return_value={"state": "completed", "final_revision": "new"}),
    )
    monkeypatch.setattr(commands, "context", lambda **_: (execution, client))
    return execution, client


@pytest.mark.asyncio
async def test_lost_run_ack_only_reads_same_operation(monkeypatch):
    execution, client = setup(monkeypatch)
    client.command.side_effect = [HarnessFailure(), {"state": "completed", "final_revision": "new"}]
    actual = await commands.run(
        None, json.dumps({"profile": "python_script", "target": "hello.py"})
    )
    assert actual.succeeded and not actual.billable
    calls = client.command.await_args_list
    assert [call.kwargs["action"] for call in calls] == ["run", "status"]
    assert calls[0].kwargs["operation_id"] == calls[1].kwargs["operation_id"]
    assert not execution.workspace.ide_reads
    execution.workspace.observe.assert_called_once_with("new")


@pytest.mark.asyncio
async def test_replayed_tool_never_posts_another_run(monkeypatch):
    _, client = setup(monkeypatch, prepared="dispatched")
    await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    client.command.assert_awaited_once()
    assert client.command.await_args.kwargs["action"] == "status"
    assert client.exchange.await_count == 1


@pytest.mark.asyncio
async def test_missing_output_stops_task_instead_of_requesting_another_command(monkeypatch):
    _, client = setup(monkeypatch)
    client.command.return_value = {
        "state": "failed",
        "final_revision": "new",
        "verification": {"status": "blocked", "reason": "output_unavailable"},
    }
    actual = await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert not actual.succeeded and not actual.billable
    assert client.failure == "verification_unavailable"
    client.command.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["verification_unavailable", "usage_limit_exceeded"])
async def test_backend_repeat_refusal_does_not_fall_back_to_status_of_a_nonexistent_command(
    monkeypatch,
    code,
):
    _, client = setup(monkeypatch)
    client.command.side_effect = HarnessFailure(code)
    with pytest.raises(HarnessFailure, match=code):
        await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert client.failure == code
    client.command.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_transport_preserves_known_verification_refusal():
    import httpx

    from service.infrastructure.harness.commands import post_command

    seen = []

    def reject(request):
        seen.append(request)
        return httpx.Response(409, json={"detail": {"code": "verification_unavailable"}})

    with pytest.raises(HarnessFailure, match="verification_unavailable"):
        await post_command(
            "http://backend/internal/harness/v1/commands",
            "PRIVATE",
            {"action": "run"},
            transport=httpx.MockTransport(reject),
        )
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_uncertain_dispatch_ack_observes_one_operation_until_real_receipt(monkeypatch):
    _, client = setup(monkeypatch)
    monkeypatch.setattr(observation.asyncio, "sleep", AsyncMock())
    client.command.side_effect = [
        {"state": "unknown"},
        HarnessFailure(),
        {"state": "running"},
        {"state": "completed", "final_revision": "actual"},
    ]
    actual = await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert actual.succeeded
    calls = client.command.await_args_list
    assert [call.kwargs["action"] for call in calls] == ["run", "status", "status", "status"]
    assert len({call.kwargs["operation_id"] for call in calls}) == 1


@pytest.mark.asyncio
async def test_unknown_command_at_deadline_stays_failed_without_replay_or_evidence(monkeypatch):
    execution, client = setup(monkeypatch)
    execution.run_deadline = SimpleNamespace(clamp=lambda _: 0)
    client.command.return_value = {"state": "unknown"}
    actual = await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert not actual.succeeded and not actual.pending and not actual.billable
    client.command.assert_awaited_once()
    execution.workspace.observe.assert_not_called()


@pytest.mark.asyncio
async def test_stop_of_unknown_command_only_addresses_the_same_operation(monkeypatch):
    execution, client = setup(monkeypatch)
    execution.cancelled = True
    client.command.side_effect = [{"state": "unknown"}, {"state": "cancelled"}]
    actual = await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert not actual.succeeded
    calls = client.command.await_args_list
    assert [call.kwargs["action"] for call in calls] == ["run", "stop"]
    assert calls[0].kwargs["operation_id"] == calls[1].kwargs["operation_id"]


@pytest.mark.asyncio
async def test_observation_does_not_retry_after_attempt_fencing(monkeypatch):
    _, client = setup(monkeypatch)
    monkeypatch.setattr(observation.asyncio, "sleep", AsyncMock())
    client.command.side_effect = [{"state": "unknown"}, HarnessFailure("harness_fenced")]
    with pytest.raises(HarnessFailure, match="harness_fenced"):
        await commands.run(None, '{"profile":"python_script","target":"hello.py"}')
    assert [c.kwargs["action"] for c in client.command.await_args_list] == ["run", "status"]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["python hello.py", "", "null"])
async def test_invalid_profile_arguments_never_prepare_or_dispatch_an_effect(monkeypatch, command):
    _, client = setup(monkeypatch)
    actual = await commands.run(
        None,
        json.dumps(
            {
                "profile": "python_script",
                "target": "hello.py",
                "command": command,
            }
        ),
    )
    assert actual.status == "invalid" and actual.failure_code == "invalid_arguments"
    assert not actual.billable and "исключи поле command" in actual.text
    client.exchange.assert_not_awaited()
    client.command.assert_not_awaited()


@pytest.mark.asyncio
async def test_backend_known_argument_refusal_syncs_journal_without_status_or_rerun(monkeypatch):
    _, client = setup(monkeypatch)
    client.load = AsyncMock()
    client.command.side_effect = HarnessFailure("harness_request_invalid")
    actual = await commands.run(None, '{"profile":"python_script","target":"a.py"}')
    assert actual.status == "invalid" and not actual.billable
    client.load.assert_awaited_once()
    client.command.assert_awaited_once()


def test_model_schema_does_not_require_mutually_exclusive_null_fields():
    schema = commands.TOOLS[0].params_json_schema
    assert schema["required"] == ["profile"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_optional_defaults_do_not_change_wire_intent_or_recovery_operation_identity(
    monkeypatch,
):
    _, client = setup(monkeypatch)
    arguments = {"profile": "python_script", "target": "a.py", "expected_stdout": "ok"}
    await commands.run(None, json.dumps(arguments))
    spec = client.command.await_args.kwargs["spec"]
    assert spec == arguments and "command" not in spec and "timeout_sec" not in spec


def test_running_receipt_is_not_no_progress_or_task_completion():
    progress = TaskProgress(active=True)
    pending = ToolCallOutcome("running", "succeeded", 0, billable=False, pending=True)
    for _ in range(8):
        progress.observe(
            {"name": "ide_command_status", "arguments": "{}"}, pending, revision="same"
        )
    assert not progress.stop_reason
    assert not progress._observations


def test_command_tools_have_no_independent_surcharge_or_private_schema_fields():
    for spec in commands.SPECS:
        assert spec.billing_name is None and not spec.dedup_safe
        assert not {"capability", "engine_id", "workspace_id", "url"} & set(
            spec.tool.params_json_schema["properties"]
        )


@pytest.mark.parametrize(
    ("provider", "capabilities"),
    [
        ("gigachat", GIGACHAT_TOOL_CAPABILITIES),
        ("routerai", OPENAI_TOOL_CAPABILITIES),
        ("openai", OPENAI_TOOL_CAPABILITIES),
    ],
)
def test_command_schemas_compile_for_supported_providers(provider, capabilities):
    compiled = compile_toolset(
        _tools_to_openai(commands.TOOLS), provider=provider, capabilities=capabilities
    )
    assert compiled.canonical_names == ("ide_run_command", "ide_command_status")
    properties = compiled.functions[0]["parameters"]["properties"]
    assert properties["target"]["nullable"] is True
    assert compiled.functions[0]["parameters"]["required"] == ["profile"]
    assert all(field["description"] for field in properties.values())
