"""Gateway usage must retain the actual provider and model, not the request label."""

import json
from contextlib import asynccontextmanager

import pytest
from openai.types.chat import ChatCompletion

from service.domain.execution.context import (
    PrivateRunResources,
    current_execution,
    use_run_execution,
)
from service.presentation.routers.gateway import openai_v1 as gateway


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,model", [("gigachat", "GigaChat-2"), ("routerai", "openai/gpt-4o")]
)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("with_usage", [False, True])
async def test_gateway_returns_one_actual_receipt(monkeypatch, provider, model, stream, with_usage):
    executions = []

    @asynccontextmanager
    async def scope():
        with use_run_execution(PrivateRunResources()) as execution:
            executions.append(execution)
            yield execution

    async def complete(*args, **kwargs):
        response = ChatCompletion(
            id="synthetic-gateway-call",
            object="chat.completion",
            created=1,
            model=model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 0}
            if with_usage
            else None,
        )
        current_execution().register_response_provider(response, provider, model)
        return response

    monkeypatch.setattr(gateway, "_gateway_execution", scope)
    monkeypatch.setattr(gateway, "_auth", lambda *_args: None)
    monkeypatch.setattr(gateway, "create_chat_completion", complete)
    data = await gateway.chat_completions(
        {"model": "requested-model", "messages": [], "stream": stream}
    )
    if stream:
        frames = []
        async for piece in data.body_iterator:
            if piece.startswith("data: {"):
                frames.append(json.loads(piece.removeprefix("data: ")))
        data = frames[-1]
    calls = data["usage"]["calls"]
    assert data["usage"]["total_tokens"] == calls[0]["total"]
    assert len(calls) == 1
    assert calls[0]["provider"] == provider
    assert calls[0]["model"] == model
    if with_usage:
        assert calls[0]["prompt"] == 2 and calls[0]["completion"] == 1
        assert not calls[0].get("estimated")
    else:
        assert calls[0]["prompt"] > 0 and calls[0]["completion"] > 0
        assert calls[0]["estimated"] is True
    assert calls[0]["receipt_id"]
    assert "requested-model" not in str(calls)
    assert executions[0].usage.billable_calls == 1
