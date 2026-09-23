from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.client.protocol import (
    GIGACHAT_TOOL_CAPABILITIES,
    OPENAI_TOOL_CAPABILITIES,
    ProviderFailureCode,
    ProviderRunSession,
    ProviderToolCompilationError,
    classify_provider_failure,
    compile_toolset,
)
from service.domain.usage_ledger import UsageKind, UsageLedger


def _tool(parameters: dict, *, dynamic: bool = False) -> dict:
    return {
        "type": "function",
        "dynamic": dynamic,
        "function": {
            "name": "lookup_record",
            "description": "Read a synthetic record.",
            "parameters": parameters,
        },
    }


def test_gigachat_compiler_preserves_nested_constraints_and_fills_only_dynamic() -> None:
    parameters = {
        "type": "object",
        "properties": {
            "filters": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {"status": {"type": "string", "enum": ["open", "closed"]}},
                    "required": ["status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["filters"],
        "additionalProperties": False,
    }

    compiled = compile_toolset(
        [_tool(parameters, dynamic=True)],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": "lookup_record"}},
    )

    payload = compiled.request_fields()
    assert set(payload) == {"functions", "function_call"}
    schema = payload["functions"][0]["parameters"]
    assert schema["properties"]["filters"]["minItems"] == 1
    assert schema["properties"]["filters"]["items"]["additionalProperties"] is False
    assert schema["properties"]["filters"]["description"] == "External tool parameter."
    assert "description" not in parameters["properties"]["filters"]


def test_required_choice_is_never_weakened_and_openai_keeps_composition() -> None:
    one = _tool({"type": "object", "properties": {}})
    forced = compile_toolset(
        [one],
        provider="gigachat",
        capabilities=GIGACHAT_TOOL_CAPABILITIES,
        tool_choice="required",
    )
    assert forced.choice == {"name": "lookup_record"}

    second = {
        **one,
        "function": {**one["function"], "name": "lookup_other"},
    }
    with pytest.raises(ProviderToolCompilationError) as caught:
        compile_toolset(
            [one, second],
            provider="gigachat",
            capabilities=GIGACHAT_TOOL_CAPABILITIES,
            tool_choice="required",
        )
    assert caught.value.reason_code == "tool_choice"

    composition = {"type": "object", "oneOf": [{"required": ["left"]}, {"required": ["right"]}]}
    compiled = compile_toolset(
        [_tool(composition)],
        provider="openai",
        capabilities=OPENAI_TOOL_CAPABILITIES,
    )
    assert compiled.functions[0]["parameters"]["oneOf"] == composition["oneOf"]


def test_provider_session_keeps_state_private_and_call_receipts_distinct() -> None:
    session = ProviderRunSession(run_id="run-safe")
    session.set_private_state("gigachat", "PRIVATE-STATE-MARKER")
    first_id = session.next_call_id(provider="gigachat")
    second_id = session.next_call_id(provider="gigachat")
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        choices=[SimpleNamespace(finish_reason="tool_calls")],
    )
    receipt = session.complete_round(
        provider="gigachat",
        model="GigaChat-2",
        response=response,
        finish_reason="tool_calls",
    )

    assert first_id != second_id != receipt.call_id
    assert session.pinned_provider == "gigachat"
    assert session.round_count == 1
    assert "PRIVATE-STATE-MARKER" not in repr(session.bounded_metadata())
    assert "call_id" not in session.bounded_metadata()

    with pytest.raises(RuntimeError, match="provider_pinning"):
        session.complete_round(provider="other", model="model", usage={})


def test_usage_ledger_does_not_merge_models_and_failure_metadata_is_bounded() -> None:
    ledger = UsageLedger()
    ledger.record_usage(
        {"prompt": 2, "completion": 1},
        provider="gigachat",
        model="GigaChat-2",
        kind=UsageKind.CHAT,
        receipt_id="one",
    )
    ledger.record_usage(
        {"prompt": 4, "completion": 2},
        provider="openai",
        model="gpt-test",
        kind=UsageKind.RESEARCH_SYNTHESIS,
        receipt_id="two",
    )
    ledger.record_usage(
        {"prompt": 99, "completion": 99},
        provider="openai",
        model="gpt-test",
        receipt_id="two",
    )

    assert len(ledger.receipts) == 2
    assert [call["model"] for call in ledger.as_token_usage()["calls"]] == [
        "GigaChat-2",
        "gpt-test",
    ]
    failure = classify_provider_failure(TimeoutError("SECRET RESPONSE BODY"), provider="gigachat")
    assert failure.code is ProviderFailureCode.TIMEOUT
    assert failure.metadata() == {"failure_code": "timeout", "retryable": True}
    assert "SECRET" not in repr(failure.metadata())
