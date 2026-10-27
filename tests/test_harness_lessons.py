"""Только один принятый урок, только к уже доступным инструментам и не на replay."""

from types import SimpleNamespace

import pytest

from service.domain.runners.harness.lessons import with_verified_lessons
from service.settings import config


@pytest.mark.asyncio
async def test_lesson_never_adds_tool_or_replaces_original_instruction(monkeypatch):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    calls = []

    async def exchange(**kwargs):
        calls.append(kwargs)
        return {
            "lessons": [
                {
                    "instruction": "Недопустимый урок",
                    "tools": [{"name": "host_shell", "advice": "Нельзя"}],
                },
                {
                    "instruction": "Прочитай файл до ответа.",
                    "tools": [{"name": "ide_read_file", "advice": "Укажи путь"}],
                },
            ]
        }

    execution = SimpleNamespace(
        cancelled=False,
        harness=SimpleNamespace(
            exchange=exchange,
            current=SimpleNamespace(
                continuation=SimpleNamespace(
                    messages=[], provider=SimpleNamespace(provider="local", model="test")
                )
            ),
        ),
    )
    original = [
        {"role": "system", "content": "Не менять права"},
        {"role": "user", "content": "Задача"},
    ]
    tools = [{"function": {"name": "ide_read_file"}}]
    prepared = await with_verified_lessons(original, tools, execution)
    assert prepared[:2] == original and len(original) == 2
    assert len(prepared) == 3 and prepared[-1]["role"] == "user"
    assert "Прочитай файл" in prepared[-1]["content"]
    assert "host_shell" not in prepared[-1]["content"]
    assert calls == [{"opcode": "lessons"}]
    assert tools == [{"function": {"name": "ide_read_file"}}]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["disabled", "resumed", "cancelled"])
async def test_no_lesson_reload_or_new_call_after_stop(monkeypatch, reason):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", reason != "disabled")

    async def forbidden(**kwargs):
        raise AssertionError("lesson_must_not_be_loaded")

    execution = SimpleNamespace(
        cancelled=reason == "cancelled",
        harness=SimpleNamespace(
            exchange=forbidden,
            current=SimpleNamespace(
                continuation=SimpleNamespace(
                    messages=[{"role": "user", "content": "Сохранённое"}]
                    if reason == "resumed"
                    else []
                )
            ),
        ),
    )
    messages = [{"role": "user", "content": "Цель"}]
    assert await with_verified_lessons(messages, [], execution) is messages
