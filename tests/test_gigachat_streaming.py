"""GigaChat streaming payload, usage and private round-state regressions."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from service.domain.client.calls import streaming
from service.domain.client.protocol import ProviderRunSession
from service.domain.client.providers.function_dialect import PROVIDER_STATE_KEY
from service.domain.runners.tool_loop import ToolRoundMixin


class _Stream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks

    def __aiter__(self):
        async def _iterate():
            for chunk in self.chunks:
                yield chunk

        return _iterate()


class _FailingStream:
    def __init__(self, first: object) -> None:
        self.first = first

    def __aiter__(self):
        async def _iterate():
            yield self.first
            raise RuntimeError("PRIVATE REMOTE BODY")

        return _iterate()


class _Completions:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.payload: dict | None = None

    async def create(self, **payload):
        self.payload = payload
        return _Stream(self.chunks)


def _client(chunks: list[object]):
    completions = _Completions(chunks)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


def _function_chunk(state_id: str) -> object:
    delta = SimpleNamespace(
        content=None,
        function_call=SimpleNamespace(name="lookup", arguments={"query": "synthetic"}),
        functions_state_id=state_id,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason="function_call")], usage=None
    )


def _usage_chunk() -> object:
    usage = SimpleNamespace(prompt_tokens=12, completion_tokens=4, total_tokens=16)
    return SimpleNamespace(choices=[], usage=usage)


@pytest.mark.asyncio
async def test_gigachat_stream_uses_functions_without_stream_options_and_keeps_usage() -> None:
    marker = "S23_OPAQUE_PROVIDER_STATE"
    client, completions = _client([_function_chunk(marker), _usage_chunk()])
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Synthetic lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Query"}},
                    "required": ["query"],
                },
            },
        }
    ]
    from service.domain.client.protocol import ProviderRoundState

    state = ProviderRoundState()
    session = ProviderRunSession(run_id="synthetic-run")

    output = [
        delta
        async for delta in streaming._stream_one_provider(
            client,
            "gigachat",
            [{"role": "user", "content": "synthetic"}],
            "GigaChat-2",
            temperature=None,
            max_tokens=32,
            round_state=state,
            include_usage=False,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "lookup"}},
            provider_session=session,
        )
    ]

    assert output == []
    assert completions.payload is not None
    assert "tools" not in completions.payload
    assert "tool_choice" not in completions.payload
    assert "stream_options" not in completions.payload
    assert completions.payload["functions"][0]["name"] == "lookup"
    assert completions.payload["function_call"] == {"name": "lookup"}
    usage = state.compatibility_payload()
    assert state.finish_reason == "tool_calls"
    assert {key: usage[key] for key in ("prompt", "completion", "total")} == {
        "prompt": 12,
        "completion": 4,
        "total": 16,
    }
    assert PROVIDER_STATE_KEY not in usage["tool_calls"][0]
    assert session.private_state("gigachat") == marker
    assert session.pinned_provider == "gigachat"
    assert session.pinned_model == "GigaChat-2"
    assert session.round_count == 1
    assert session.rounds[0].pin_source.value == "stream_delta"
    assert marker not in json.dumps(usage)


@pytest.mark.asyncio
async def test_tool_round_keeps_provider_state_out_of_events() -> None:
    marker = "S23_OPAQUE_PROVIDER_STATE"

    async def _invoke(_ctx, _arguments):
        return "ok"

    tool = SimpleNamespace(name="lookup", on_invoke_tool=_invoke)

    class _Owner(ToolRoundMixin):
        name = "test"

    convo: list[dict] = []
    calls = [
        {
            "id": "call_legacy_0",
            "name": "lookup",
            "arguments": "{}",
            PROVIDER_STATE_KEY: marker,
        }
    ]

    events = [
        event
        async for event in _Owner()._execute_tool_round(
            convo, calls, {"lookup": tool}, None, "", set(), round_number=1
        )
    ]

    assert PROVIDER_STATE_KEY not in convo[0]
    serialized = json.dumps(
        [{"data": event.data, "metadata": event.metadata} for event in events],
        ensure_ascii=False,
    )
    assert marker not in serialized
    assert PROVIDER_STATE_KEY not in serialized


@pytest.mark.asyncio
async def test_function_only_delta_pins_before_a_late_stream_failure() -> None:
    marker = "S23_LATE_FAILURE_STATE"

    class _LateFailureCompletions:
        async def create(self, **payload):
            return _FailingStream(_function_chunk(marker))

    client = SimpleNamespace(chat=SimpleNamespace(completions=_LateFailureCompletions()))
    session = ProviderRunSession(run_id="late-failure")
    from service.domain.client.protocol import ProviderRoundState

    state = ProviderRoundState()
    tool = {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Synthetic lookup",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Query"}},
                "required": ["query"],
            },
        },
    }

    with pytest.raises(RuntimeError, match="PRIVATE REMOTE BODY"):
        _ = [
            delta
            async for delta in streaming._stream_one_provider(
                client,
                "gigachat",
                [{"role": "user", "content": "synthetic"}],
                "GigaChat-2",
                temperature=None,
                max_tokens=32,
                round_state=state,
                include_usage=False,
                tools=[tool],
                provider_session=session,
            )
        ]

    assert session.pinned_provider == "gigachat"
    assert session.private_state("gigachat") is None  # state commits only after a complete round
    assert marker not in json.dumps(state.compatibility_payload())
