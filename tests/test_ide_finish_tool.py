import hashlib
import json
from types import SimpleNamespace

import pytest

from service.application.agent_execution_service import _finalize_reply
from service.application.reply_assembler import ReplyAssembler
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.tools.ide.finish import SPEC, TOOL, ide_finish_task, summary_for_result
from service.domain.tools.ide.tools import ide_write

REF = {"ide_context": {"repository_id": "private", "generation": "a" * 64}}


def test_model_schema_declares_the_same_short_report_limit_as_runtime():
    summary = TOOL.params_json_schema["properties"]["summary"]
    assert summary["minLength"] == 1
    assert summary["maxLength"] == 280
    assert TOOL.params_json_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_confirmed_write_then_finish_projects_only_the_report_in_summary(monkeypatch):
    calls = []

    async def acknowledge(ref, endpoint, payload):
        calls.append(endpoint)
        return dict(
            written=True,
            path=payload["path"],
            kind="file",
            size=len(payload["content"].encode()),
            digest=hashlib.sha256(payload["content"].encode()).hexdigest(),
        )

    monkeypatch.setattr("service.domain.tools.ide.tools.call", acknowledge)
    report = "Добавлен README. Проверки не запускались."
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        receipt = await ide_write(
            None, json.dumps(dict(path="README.md", content="# Project", base_digest=""))
        )
        assert receipt.succeeded and json.loads(receipt.text)["written"] is True
        await ide_finish_task(None, json.dumps({"summary": report, "outcome": "changed"}))
        assembler = ReplyAssembler(execution.usage)
        assembler.reply_parts.append("Подробный ответ с кодом для истории Чата.")
        result = await _finalize_reply(
            reply_assembler=assembler,
            metadata={},
            timings=SimpleNamespace(as_meta=lambda: {}),
            workspace_ref=REF,
            resolved_model="test-model",
        )
    assert result["metadata"]["ide_summary"] == report
    assert result["metadata"]["ide_files_written"] == 1
    assert result["metadata"]["ide_write_unconfirmed"] is False
    assert result["reply"] == "Подробный ответ с кодом для истории Чата."
    # Finishing adds no remote workspace request (and never another LLM request).
    assert calls == ["ide/agent/write"]


@pytest.mark.asyncio
async def test_terminal_tool_is_local_unbilled_and_run_scoped():
    assert SPEC.billing_name is None
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        result = await ide_finish_task(
            None,
            json.dumps(
                {
                    "summary": "Инструкция запуска описана в ответе, файлы не изменены.",
                    "outcome": "unchanged",
                }
            ),
        )
        assert json.loads(result) == {"summary_recorded": True}
        assert (
            summary_for_result(execution)
            == "Инструкция запуска описана в ответе, файлы не изменены."
        )
        assert not execution.workspace.ide_writes
        assert "Добавлена" not in repr(execution.workspace)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        assert execution.workspace.ide_summary is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", ["", " ", " x", "x\ncode", "x\tcode", "x\u2028code", "x" * 281, 1, {}]
)
async def test_invalid_summary_never_replaces_a_valid_one(value):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.workspace.ide_summary = "Предыдущий итог."
        result = await ide_finish_task(None, json.dumps({"summary": value, "outcome": "unchanged"}))
        assert isinstance(result, ToolCallOutcome) and not result.billable
        assert execution.workspace.ide_summary == "Предыдущий итог."


@pytest.mark.asyncio
async def test_summary_is_not_available_outside_private_ide_context():
    with use_run_execution(PrivateRunResources()) as execution:
        assert isinstance(await ide_finish_task(None, '{"summary":"Done"}'), ToolCallOutcome)
        assert execution.workspace.ide_summary is None


@pytest.mark.asyncio
async def test_later_ambiguous_mutation_retires_the_previous_summary(monkeypatch):
    async def invalid_ack(*args):
        return {"written": True}

    monkeypatch.setattr("service.domain.tools.ide.tools.call", invalid_ack)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        await ide_finish_task(None, '{"summary":"Готово.","outcome":"unchanged"}')
        await ide_write(None, '{"path":"a.py","content":"x","base_digest":""}')
        assert execution.workspace.ide_summary is None
        assert "не подтверждён" in summary_for_result(execution)


@pytest.mark.asyncio
@pytest.mark.parametrize("report", [None, "Добавлена инструкция; проверки не запускались."])
@pytest.mark.parametrize("awaiting", [False, True])
async def test_terminal_projection_keeps_full_chat_reply_and_does_not_summarize_a_pause(
    report, awaiting
):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.workspace.ide_summary = report
        execution.workspace.ide_writes["a.py"] = "b" * 64
        assembler = ReplyAssembler(execution.usage)
        assembler.reply_parts.append("Full Chat reply with detailed explanation and code.")
        result = await _finalize_reply(
            reply_assembler=assembler,
            metadata={"awaiting_confirmation": awaiting},
            timings=SimpleNamespace(as_meta=lambda: {}),
            workspace_ref=REF,
            resolved_model="test-model",
        )
        if awaiting:
            assert "ide_summary" not in result["metadata"]
        else:
            assert result["metadata"]["ide_summary"] == (report or summary_for_result(execution))
        assert result["metadata"]["ide_files_written"] == 1
        assert result.get("workspace_artifacts", []) == []
        if not awaiting:
            assert result["reply"] == "Full Chat reply with detailed explanation and code."


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["{}", "[]", "{", '{"summary":"x","source":"code"}'])
async def test_terminal_tool_rejects_malformed_and_extra_arguments(raw):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        assert isinstance(await ide_finish_task(None, raw), ToolCallOutcome)
        assert execution.workspace.ide_summary is None


def test_missing_tool_does_not_invent_execution_or_success():
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        assert "не передал краткий итог" in summary_for_result(execution)
        execution.workspace.ide_writes["a.py"] = "b" * 64
        assert "не закоммичены" in summary_for_result(execution)
        execution.workspace.ide_unconfirmed = True
        assert "не подтверждён" in summary_for_result(execution)


@pytest.mark.asyncio
@pytest.mark.parametrize("unconfirmed", [False, True])
async def test_finish_cannot_claim_created_script_without_confirmed_write(unconfirmed):
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.workspace.ide_unconfirmed = unconfirmed
        result = await ide_finish_task(
            None,
            json.dumps(
                {
                    "summary": "Создан скрипт hello_world.py в папке src/.",
                    "outcome": "changed",
                }
            ),
        )
        assert isinstance(result, ToolCallOutcome) and not result.billable
        assert execution.workspace.ide_summary is None
        assert "ide_result_not_confirmed" in result.text


@pytest.mark.asyncio
async def test_unchanged_cannot_hide_confirmed_mutation():
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        execution.workspace.ide_writes["a.py"] = "b" * 64
        result = await ide_finish_task(None, '{"summary":"Нет изменений.","outcome":"unchanged"}')
        assert isinstance(result, ToolCallOutcome)
        assert execution.workspace.ide_summary is None


@pytest.mark.asyncio
async def test_rejected_finish_can_be_followed_by_real_script_creation(monkeypatch):
    async def acknowledge(ref, endpoint, payload):
        return dict(
            written=True,
            path=payload["path"],
            kind="file",
            size=len(payload["content"].encode()),
            digest=hashlib.sha256(payload["content"].encode()).hexdigest(),
        )

    monkeypatch.setattr("service.domain.tools.ide.tools.call", acknowledge)
    report = {"summary": "Создан hello_world.py.", "outcome": "changed"}
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        assert isinstance(await ide_finish_task(None, json.dumps(report)), ToolCallOutcome)
        await ide_write(
            None,
            json.dumps(
                {"path": "hello_world.py", "base_digest": "", "content": 'print("Hello, world!")\n'}
            ),
        )
        result = await ide_finish_task(None, json.dumps(report))
        assert json.loads(result) == {"summary_recorded": True}
        assert list(execution.workspace.ide_writes) == ["hello_world.py"]
        assert summary_for_result(execution) == report["summary"]
