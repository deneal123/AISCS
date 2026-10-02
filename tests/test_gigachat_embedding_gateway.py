"""GigaChat embeddings/token-count gateway contract.

Focused tests for the pinned-embedding gateway work:

* GigaChat declares ``EmbeddingsGigaR`` dimension 2560 and a 4096-token window;
* an explicit ``provider:model`` pin is STRICT — an unavailable model fails before
  any provider call instead of silently selecting the first embedding model;
* ``POST /v1/tokens/count`` uses the same admitted provider client;
* unsupported OpenAI ``dimensions`` is not forwarded to GigaChat;
* embedding responses are validated (model, count, index uniqueness, exact
  dimension, finite components);
* the pre-existing unpinned fallback is preserved.

All provider clients here are local fakes: no network, no OAuth, no paid calls.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from service.domain.client.model_catalog import (
    CapabilityEvidenceSource,
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.provider_admission import RunProviderAdmission, RunProviderSnapshot
from service.domain.client.providers import gigachat
from service.domain.client.registry import get_spec
from service.presentation.routers.gateway import openai_v1


# --------------------------------------------------------------------------- #
# Local fakes
# --------------------------------------------------------------------------- #
class _Embeddings:
    def __init__(self, owner: _FakeClient):
        self._owner = owner

    async def create(self, **kwargs):
        self._owner.embedding_calls.append(kwargs)
        return self._owner.embedding_response


class _FakeClient:
    """Minimal AsyncOpenAI-shaped double: no transport, records every call."""

    def __init__(self, embedding_response=None, post_response=None):
        self.embedding_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self.embedding_response = embedding_response or _embedding_response()
        self.post_response = post_response
        self.embeddings = _Embeddings(self)

    async def post(self, path, *, cast_to=None, body=None, **kwargs):
        self.post_calls.append({"path": path, "cast_to": cast_to, "body": body})
        return self.post_response


def _embedding_response(*, model="EmbeddingsGigaR", vectors=None, indices=None):
    vectors = vectors if vectors is not None else [[0.1] * 2560]
    indices = indices if indices is not None else list(range(len(vectors)))
    return SimpleNamespace(
        model=model,
        data=[
            SimpleNamespace(index=index, embedding=vector)
            for index, vector in zip(indices, vectors, strict=True)
        ],
    )


def _record(model, *, dimension=None, capabilities=frozenset({"embeddings"})):
    return ProviderModelRecord(
        model_id=model,
        capabilities=capabilities,
        evidence_source=CapabilityEvidenceSource.LOCAL_PROFILE,
        embedding_dimension=dimension,
    )


def _admission(*records, client=None, provider="gigachat"):
    client = client or _FakeClient()
    catalog = ProviderModelCatalog(
        provider=provider,
        models=tuple(record.model_id for record in records),
        records=records,
        source=ModelCatalogSource.LIVE,
        status=ModelCatalogStatus.AVAILABLE,
        fresh=True,
    )
    return RunProviderAdmission(
        RunProviderSnapshot(
            catalogs={provider: catalog},
            records={provider: records},
            clients={provider: client},
            owner_index={record.model_id: provider for record in records},
            provider_order=(provider,),
            active_provider=provider,
            configuration_generation="generation",
        )
    )


def _execution(admission):
    return SimpleNamespace(provider_admission=admission)


class _FakeExecutionScope:
    def __init__(self, execution):
        self._execution = execution

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._execution

    async def __aexit__(self, *exc):
        return False


@pytest.fixture()
def gateway_client(monkeypatch):
    """TestClient with the gateway enabled and a settable fake execution."""

    from service.settings import config

    key = "test-gateway-key"
    monkeypatch.setattr(config.agents, "llm_gateway_enabled", True, raising=False)
    monkeypatch.setattr(config.agents, "llm_gateway_api_key", key, raising=False)
    return TestClient(_app(), headers={"Authorization": f"Bearer {key}"})


def _app():
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(openai_v1.v1_router)
    return app


def _install_execution(monkeypatch, execution):
    monkeypatch.setattr(openai_v1, "_gateway_execution", _FakeExecutionScope(execution))


# --------------------------------------------------------------------------- #
# 1. Declared embedding metadata
# --------------------------------------------------------------------------- #
def test_gigachat_declares_gigar_dimension_and_window():
    spec = get_spec("gigachat")
    assert spec.embedding_dimension_for("EmbeddingsGigaR") == 2560
    assert spec.embedding_context_window_for("EmbeddingsGigaR") == 4096
    assert spec.supports_embedding_dimensions is False
    assert spec.token_count_path == "/tokens/count"
    # The older OpenAI-compatible default stays declared.
    assert spec.embedding_dimension_for("Embeddings") == 1024


def test_context_window_profile_requires_embeddings_capability():
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(
            gigachat.SPEC,
            embedding_context_windows=(("GigaChat-2", 4096),),
        )


# --------------------------------------------------------------------------- #
# 2. Strict ``provider:model`` pin
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_explicit_pin_missing_model_fails_before_any_api_call():
    client = _FakeClient()
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="embedding operation unsupported"):
        await openai_v1._embed(
            {"model": "gigachat:Embeddings-Missing", "input": ["hello"]},
            _execution(admission),
        )

    assert client.embedding_calls == []


@pytest.mark.asyncio
async def test_explicit_pin_present_model_calls_the_pinned_model():
    client = _FakeClient()
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    await openai_v1._embed(
        {"model": "gigachat:EmbeddingsGigaR", "input": ["hello"]},
        _execution(admission),
    )

    assert len(client.embedding_calls) == 1
    assert client.embedding_calls[0]["model"] == "EmbeddingsGigaR"


@pytest.mark.asyncio
async def test_unpinned_embedding_keeps_first_model_fallback():
    client = _FakeClient(embedding_response=_embedding_response(vectors=[[0.0] * 2560]))
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    await openai_v1._embed({"model": "irrelevant", "input": ["hello"]}, _execution(admission))

    # No known prefix → active provider, first compatible embedding model.
    assert client.embedding_calls[0]["model"] == "EmbeddingsGigaR"


def test_strict_pin_is_distinct_admission_cache_entry():
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560))
    pick_calls = 0

    def picker(models, prefer):
        nonlocal pick_calls
        pick_calls += 1
        return models[0] if models else None

    lenient = admission.admit(
        "gigachat",
        operation=openai_v1.ProviderOperation.EMBEDDINGS,
        prefer="Embeddings-Missing",
        pick_model=picker,
    )
    strict = admission.admit(
        "gigachat",
        operation=openai_v1.ProviderOperation.EMBEDDINGS,
        prefer="Embeddings-Missing",
        require_preferred=True,
        pick_model=picker,
    )

    assert lenient.model == "EmbeddingsGigaR"  # legacy behaviour preserved
    assert strict.model is None
    assert strict.failure_code == "no_compatible_model"


# --------------------------------------------------------------------------- #
# 3. ``/v1/tokens/count``
# --------------------------------------------------------------------------- #
def test_tokens_count_endpoint_returns_openai_list(monkeypatch, gateway_client):
    client = _FakeClient(post_response={"tokens": 7})
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)
    _install_execution(monkeypatch, _execution(admission))

    response = gateway_client.post(
        "/v1/tokens/count",
        json={"model": "gigachat:EmbeddingsGigaR", "input": ["abcdefg"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert body["model"] == "EmbeddingsGigaR"
    assert body["data"] == [{"object": "token_count", "index": 0, "tokens": 7}]
    assert client.post_calls == [
        {
            "path": "/tokens/count",
            "cast_to": object,
            "body": {"model": "EmbeddingsGigaR", "input": ["abcdefg"]},
        }
    ]


def test_tokens_count_endpoint_fails_closed_without_provider_support(
    monkeypatch, gateway_client
):
    client = _FakeClient(post_response={"tokens": 1})
    admission = _admission(
        _record("plain-embed", dimension=8, capabilities=frozenset({"embeddings"})),
        client=client,
        provider="openrouter",
    )
    _install_execution(monkeypatch, _execution(admission))

    response = gateway_client.post(
        "/v1/tokens/count",
        json={"model": "openrouter:plain-embed", "input": ["x"]},
    )

    assert response.status_code == 502
    assert client.post_calls == []


def test_tokens_count_rejects_model_mismatch(monkeypatch, gateway_client):
    client = _FakeClient(post_response={"tokens": 3})
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)
    _install_execution(monkeypatch, _execution(admission))

    response = gateway_client.post(
        "/v1/tokens/count",
        json={"model": "gigachat:Embeddings-Missing", "input": ["x"]},
    )

    assert response.status_code == 502
    assert client.post_calls == []


def test_token_count_values_normalizes_provider_shapes():
    assert openai_v1._token_count_values({"tokens": 5}, count=1) == [5]
    assert openai_v1._token_count_values(
        {"data": [{"tokens": 5}, {"token_count": 6}]}, count=2
    ) == [5, 6]
    assert openai_v1._token_count_values([[7]], count=1) == [7]
    with pytest.raises(RuntimeError):
        openai_v1._token_count_values({"tokens": 5}, count=2)
    with pytest.raises(RuntimeError):
        openai_v1._token_count_values({"tokens": -1}, count=1)


# --------------------------------------------------------------------------- #
# 4. ``dimensions`` forwarding
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_gigachat_dimensions_field_is_not_forwarded():
    client = _FakeClient()
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    await openai_v1._embed(
        {"model": "gigachat:EmbeddingsGigaR", "input": ["hi"], "dimensions": 2560},
        _execution(admission),
    )

    assert "dimensions" not in client.embedding_calls[0]


@pytest.mark.asyncio
async def test_other_providers_still_receive_dimensions():
    client = _FakeClient(
        embedding_response=_embedding_response(
            model="plain-embed", vectors=[[0.1] * 8]
        )
    )
    admission = _admission(
        _record("plain-embed", dimension=8),
        client=client,
        provider="openrouter",
    )

    await openai_v1._embed(
        {"model": "openrouter:plain-embed", "input": ["hi"], "dimensions": 8},
        _execution(admission),
    )

    assert client.embedding_calls[0]["dimensions"] == 8


# --------------------------------------------------------------------------- #
# 5. Embedding response validation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_embedding_response_model_mismatch_is_rejected():
    client = _FakeClient(embedding_response=_embedding_response(model="OtherModel"))
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="embedding model mismatch"):
        await openai_v1._embed(
            {"model": "gigachat:EmbeddingsGigaR", "input": ["hi"]},
            _execution(admission),
        )


@pytest.mark.asyncio
async def test_embedding_response_count_mismatch_is_rejected():
    client = _FakeClient(embedding_response=_embedding_response(vectors=[[0.1] * 2560]))
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="embedding count mismatch"):
        await openai_v1._embed(
            {"model": "gigachat:EmbeddingsGigaR", "input": ["one", "two"]},
            _execution(admission),
        )


@pytest.mark.asyncio
async def test_embedding_response_duplicate_index_is_rejected():
    client = _FakeClient(
        embedding_response=_embedding_response(
            vectors=[[0.1] * 2560, [0.2] * 2560], indices=[0, 0]
        )
    )
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="embedding indices are inconsistent"):
        await openai_v1._embed(
            {"model": "gigachat:EmbeddingsGigaR", "input": ["one", "two"]},
            _execution(admission),
        )


@pytest.mark.asyncio
async def test_embedding_response_exact_dimension_is_required():
    client = _FakeClient(embedding_response=_embedding_response(vectors=[[0.1] * 1024]))
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="embedding dimension mismatch"):
        await openai_v1._embed(
            {"model": "gigachat:EmbeddingsGigaR", "input": ["hi"]},
            _execution(admission),
        )


@pytest.mark.asyncio
async def test_embedding_response_non_finite_is_rejected():
    bad = [0.1] * 2560
    bad[0] = float("nan")
    client = _FakeClient(embedding_response=_embedding_response(vectors=[bad]))
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    with pytest.raises(RuntimeError, match="non-finite"):
        await openai_v1._embed(
            {"model": "gigachat:EmbeddingsGigaR", "input": ["hi"]},
            _execution(admission),
        )


@pytest.mark.asyncio
async def test_embedding_response_accepted_when_exact():
    client = _FakeClient()
    admission = _admission(_record("EmbeddingsGigaR", dimension=2560), client=client)

    response = await openai_v1._embed(
        {"model": "gigachat:EmbeddingsGigaR", "input": ["hi"]},
        _execution(admission),
    )

    assert response.model == "EmbeddingsGigaR"
    assert response.data[0].index == 0
