"""Память использует общий допуск и не смешивает модели/пространства векторов."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import APIStatusError, AsyncOpenAI
from openai.types.chat import ChatCompletion

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.presentation.routers.gateway import memory


class Admission:
    def __init__(self, clients, dimensions):
        self.clients = clients
        records = {
            provider: [
                SimpleNamespace(
                    model_id=model,
                    embedding_dimension=dimension,
                    supports=lambda cap: cap == "embeddings",
                )
                for model, dimension in models.items()
            ]
            for provider, models in dimensions.items()
        }
        self.snapshot = SimpleNamespace(provider_order=tuple(clients), records=records)

    def admit(self, provider, *, prefer, **kwargs):
        record = next(r for r in self.snapshot.records[provider] if r.model_id == prefer)
        return SimpleNamespace(
            provider=provider,
            model=prefer,
            client=self.clients[provider],
            admitted=True,
            embedding_dimension=record.embedding_dimension,
        )


def client(handler):
    return AsyncOpenAI(
        api_key="synthetic",
        base_url="http://synthetic/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def response(dim):
    return httpx.Response(
        200,
        json={
            "object": "list",
            "model": "embed",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
            "data": [{"object": "embedding", "index": 0, "embedding": [0.25] * dim}],
        },
    )


@pytest.fixture(autouse=True)
def reset_cooldown():
    memory._COOLDOWN.clear()
    yield
    memory._COOLDOWN.clear()


@pytest.mark.asyncio
async def test_failed_model_next_request_changes_space_without_repeating_unknown_call():
    seen = []

    def primary(req):
        seen.append("primary")
        return httpx.Response(503, json={"error": {"message": "synthetic"}})

    def backup(req):
        seen.append("backup")
        return response(3)

    clients = {"primary": client(primary), "backup": client(backup)}
    execution = SimpleNamespace(
        provider_admission=Admission(
            clients,
            {
                "primary": {"embed": 2},
                "backup": {"embed": 3},
            },
        )
    )
    payload = {"model": memory.EMBEDDING_MODEL, "input": ["Синтетический факт"]}
    try:
        with pytest.raises(RuntimeError, match="memory_embedding_call_failed"):
            await memory.embed(payload, execution, preferred="primary:embed")
        assert seen == ["primary"]
        result = await memory.embed(payload, execution, preferred="primary:embed")
        assert result["model"] == "backup:embed"
        assert result["gpthub_embedding_dimension"] == 3
        assert len(result["gpthub_embedding_space"]) == 32
        assert seen == ["primary", "backup"]
    finally:
        for sdk in clients.values():
            await sdk.close()


@pytest.mark.asyncio
async def test_equal_dimensions_do_not_mean_same_space():
    clients = {provider: client(lambda req: response(2)) for provider in ("a", "b")}
    execution = SimpleNamespace(
        provider_admission=Admission(clients, {provider: {"embed": 2} for provider in clients})
    )
    try:
        a = await memory.embed({"input": "Факт"}, execution, preferred="a:embed")
        b = await memory.embed({"input": "Факт"}, execution, preferred="b:embed")
        assert a["gpthub_embedding_space"] != b["gpthub_embedding_space"]
    finally:
        for sdk in clients.values():
            await sdk.close()


@pytest.mark.asyncio
async def test_non_admitted_provider_is_never_contacted():
    execution = SimpleNamespace(provider_admission=Admission({}, {}))
    with pytest.raises(RuntimeError, match="memory_embedder_unavailable"):
        await memory.embed({"input": "Факт"}, execution, preferred="disabled:embed")


@pytest.mark.asyncio
async def test_wrong_dimension_never_receives_space_receipt():
    sdk = client(lambda req: response(3))
    execution = SimpleNamespace(provider_admission=Admission({"a": sdk}, {"a": {"embed": 2}}))
    try:
        with pytest.raises(RuntimeError, match="memory_embedding_dimension_mismatch"):
            await memory.embed({"input": "Факт"}, execution, preferred="a:embed")
    finally:
        await sdk.close()


@pytest.mark.asyncio
async def test_explicit_model_rejection_uses_other_provider_in_same_request():
    seen = []

    def missing(req):
        seen.append("missing")
        return httpx.Response(404, json={"error": {"message": "model unavailable"}})

    def available(req):
        seen.append("available")
        return response(3)

    clients = {"a": client(missing), "b": client(available)}
    execution = SimpleNamespace(
        provider_admission=Admission(
            clients,
            {
                "a": {"embed": 2},
                "b": {"embed": 3},
            },
        )
    )
    try:
        result = await memory.embed({"input": "Факт"}, execution, preferred="a:embed")
        assert result["model"] == "b:embed"
        assert seen == ["missing", "available"]
    finally:
        for sdk in clients.values():
            await sdk.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 503])
async def test_text_failover_is_bounded_and_preserves_actual_usage(monkeypatch, status):
    seen = []

    class ChatAdmission:
        snapshot = SimpleNamespace(provider_order=("a", "b"), release=Mock())

        def admit(self, provider, **kwargs):
            return SimpleNamespace(admitted=True, provider=provider, model="chat")

    with use_run_execution(PrivateRunResources()) as execution:
        execution.provider_admission = ChatAdmission()

        async def complete(**kwargs):
            provider = kwargs["provider"]
            assert kwargs["pin_provider"] == provider
            seen.append(provider)
            if provider == "a":
                raise APIStatusError(
                    "synthetic",
                    response=httpx.Response(
                        status, request=httpx.Request("POST", "http://synthetic")
                    ),
                    body={},
                )
            response = ChatCompletion(
                id="synthetic",
                object="chat.completion",
                created=1,
                model="chat",
                choices=[
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Ответ"},
                        "finish_reason": "stop",
                    }
                ],
                usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            )
            execution.register_response_provider(response, provider, "chat")
            return response

        monkeypatch.setattr("service.domain.client.create_chat_completion", complete)
        payload = {"model": memory.CHAT_MODEL, "messages": [{"role": "user", "content": "Факт"}]}
        if status == 503:
            with pytest.raises(RuntimeError, match="memory_model_call_failed"):
                await memory.complete(payload, execution)
            assert seen == ["a"]
            assert execution.usage.billable_calls == 0
        else:
            result = await memory.complete(payload, execution)
            assert seen == ["a", "b"]
            assert result.usage.provider == "b" and result.usage.model == "chat"
            assert execution.usage.billable_calls == 1


@pytest.mark.asyncio
async def test_profile_requires_gateway_auth_and_never_performs_paid_work(monkeypatch):
    import json

    from fastapi import HTTPException

    from service.presentation.routers.gateway import openai_v1 as gateway

    monkeypatch.setattr(gateway.config.agents, "llm_gateway_enabled", True)
    monkeypatch.setattr(gateway.config.agents, "llm_gateway_api_key", "synthetic")
    entered = []

    @asynccontextmanager
    async def scope():
        entered.append(1)
        yield SimpleNamespace(provider_admission=Admission({}, {}))

    monkeypatch.setattr(gateway, "_gateway_execution", scope)
    with pytest.raises(HTTPException) as error:
        await gateway.memory_profile(None)
    assert error.value.status_code == 401 and not entered
    result = await gateway.memory_profile("Bearer synthetic")
    assert result.headers["Cache-Control"] == "no-store"
    assert json.loads(result.body) == {"chat": [], "embedding": []}
    assert entered == [1]


@pytest.mark.asyncio
async def test_embedding_deadline_covers_whole_fallback_sequence(monkeypatch):
    from service.presentation.routers.gateway import openai_v1 as gateway

    calls = []

    async def wait(*args, **kwargs):
        calls.append(1)
        await asyncio.Event().wait()

    monkeypatch.setattr(memory, "embed", wait)
    monkeypatch.setattr(memory, "EMBEDDING_TIMEOUT_SEC", 0.01)
    with pytest.raises(TimeoutError):
        await gateway._embed({"model": memory.EMBEDDING_MODEL, "input": "Факт"}, object())
    assert calls == [1]
