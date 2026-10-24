"""Реальная генерация ограниченной рекомендации; не приёмка worker/БД или эффектов."""

import asyncio
import json
import os
import sys


async def exercise(key):
    os.environ["AGENTS__LOCAL_API_KEY"] = key
    os.environ["AGENTS__LOCAL_BASE_URL"] = "http://local-llm:8080/v1"
    from service.domain.client import create_chat_completion
    from service.domain.client.calls.harness_transport import message_projection
    from service.domain.client.providers.local import MODEL_ID
    from service.domain.execution.context import PrivateRunResources, use_run_execution
    from service.domain.execution.model import invoke_model_call
    from service.domain.runners.harness.refinement import _INSTRUCTIONS, render_refinement
    from service.shared.harness_refinement import (
        PROPOSAL_TOOL,
        proposal_from_message,
        proposal_tool,
    )

    with use_run_execution(PrivateRunResources()) as execution:
        result = await invoke_model_call(
            create_chat_completion,
            execution=execution,
            model=MODEL_ID,
            kind="meta_usage",
            pin_provider="local",
            temperature=0.1,
            max_tokens=512,
            messages=[
                {"role": "system", "content": _INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "goal": "Прочитай a.py до ответа.",
                            "failure": "missing_call",
                            "allowed_tools": ["ide_read_file"],
                            "required_tools": ["ide_read_file"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            tools=[proposal_tool()],
            tool_choice={"type": "function", "function": {"name": PROPOSAL_TOOL}},
        )
        assert result.finish_reason == "tool_calls", "refinement_terminal_invalid"
        candidate = proposal_from_message(
            message_projection(result.response).model_dump(mode="json")
        )
        assert all(tool.name == "ide_read_file" for tool in candidate.tools), (
            "unknown_tool_proposed"
        )
        assert any("а" <= char.lower() <= "я" for char in candidate.instruction), (
            "russian_instruction_missing"
        )
        assert "не расширяет полномочия" in render_refinement(candidate), "guard_missing"
        assert len(execution.usage.receipts) == 1 and result.usage.total > 0, "usage_invalid"
        return {
            "refinement_proposal": True,
            "provider": result.provider,
            "model_calls": 1,
            "tokens": result.usage.total,
            "adopted": False,
            "worker_or_journal_acceptance": False,
        }


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(exercise(json.load(sys.stdin)["key"]))), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, AssertionError) else "refinement_probe_failed"
        print(json.dumps({"failure": code}), flush=True)
        raise SystemExit(1) from None
