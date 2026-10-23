"""Смена модели не смешивает векторы и не удаляет исходную память."""

import json

from uuid import uuid4

import httpx
import pytest

from openai import OpenAI
from qdrant_client import QdrantClient

from memos.api.handlers.write_receipt import indexed_results
from memos.configs.embedder import UniversalAPIEmbedderConfig
from memos.configs.vec_db import QdrantVecDBConfig
from memos.embedders.space import SpaceVector
from memos.embedders.universal_api import UniversalAPIEmbedder
from memos.memories.textual.item import TreeNodeTextualMemoryMetadata
from memos.memories.textual.tree_text_memory.retrieve.retrieve_utils import cosine_similarity_matrix
from memos.vec_dbs.item import VecDBItem
from memos.vec_dbs.spaces import SpaceAwareQdrantVecDB


def test_space_survives_metadata_validation_serialization_and_assignment():
    vector = SpaceVector([0.1, 0.2], "a" * 32)
    meta = TreeNodeTextualMemoryMetadata(embedding=vector)
    assert meta.model_dump()["embedding_space"] == "a" * 32
    restored = TreeNodeTextualMemoryMetadata.model_validate_json(meta.model_dump_json())
    assert restored.embedding_space == "a" * 32
    assert restored.embedding.space == "a" * 32
    restored.embedding = SpaceVector([0.3] * 3, "b" * 32)
    assert restored.model_dump()["embedding_space"] == "b" * 32
    restored.embedding = [0.1, 0.2]
    assert restored.embedding_space is None


def test_separate_indexes_even_for_equal_dimensions(monkeypatch):
    memory = QdrantClient(":memory:")
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **kw: memory)
    store = SpaceAwareQdrantVecDB(
        QdrantVecDBConfig(
            collection_name="legacy_test",
            vector_dimension=2,
            distance_metric="cosine",
        )
    )
    ids = [str(uuid4()) for _ in range(3)]
    for id, space, dimension in zip(ids, ["a" * 32, "b" * 32, "c" * 32], [2, 2, 3], strict=True):
        store.add(
            [
                VecDBItem(
                    id=id,
                    vector=[0.25] * dimension,
                    payload={"embedding_space": space, "user_name": "synthetic"},
                )
            ]
        )
    assert [r.id for r in store.search(SpaceVector([1, 1], "a" * 32), 5)] == ids[:1]
    assert [r.id for r in store.search(SpaceVector([1, 1], "b" * 32), 5)] == ids[1:2]
    assert [r.id for r in store.search(SpaceVector([1, 1, 1], "c" * 32), 5)] == ids[2:]
    assert store.count({"user_name": "synthetic"}) == 3
    # После пересоздания клиента физические индексы остаются доступны.
    again = SpaceAwareQdrantVecDB(store.config)
    assert len(again.get_by_ids(ids)) == 3
    # Одинаковый memory ID в двух поколениях должен читаться по нужному пространству.
    again.add(
        [
            VecDBItem(
                id=ids[0],
                vector=[0.5] * 2,
                payload={"embedding_space": "b" * 32, "user_name": "synthetic"},
            )
        ]
    )
    assert again.get_for_space(ids[0], "a" * 32).vector.space == "a" * 32
    assert again.get_for_space(ids[0], "b" * 32).vector.space == "b" * 32
    again.delete(ids[:1])
    assert again.count() == 2
    memory.close()


def test_cosine_does_not_mix_models_or_dimensions():
    vectors = [
        SpaceVector([1, 0], "a" * 32),
        SpaceVector([1, 0], "b" * 32),
        SpaceVector([1, 0, 0], "c" * 32),
        SpaceVector([1, 0], "a" * 32),
    ]
    matrix = cosine_similarity_matrix(vectors)
    assert matrix[0, 1] == matrix[0, 2] == 0
    assert matrix[0, 3] == 1


def make_embedder(handler):
    embedder = UniversalAPIEmbedder(
        UniversalAPIEmbedderConfig(
            provider="openai",
            api_key="synthetic",
            base_url="http://synthetic/v1",
            model_name_or_path="gpthub-memory-embedding",
        )
    )
    embedder.client.close()
    embedder.client = OpenAI(
        api_key="synthetic",
        base_url="http://synthetic/v1",
        timeout=15,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return embedder


def test_real_sdk_preserves_space_and_orders_vectors_without_asyncio_run():
    def handle(request):
        body = json.loads(request.content)
        assert body["model"] == "gpthub-memory-embedding"
        assert request.extensions["timeout"]["read"] == 15
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "provider:embedding",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0, 1]},
                    {"object": "embedding", "index": 0, "embedding": [1, 0]},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
                "gpthub_embedding_space": "a" * 32,
            },
        )

    embedder = make_embedder(handle)
    try:
        vectors = embedder.embed(["Первая реплика", "Вторая реплика"])
        assert vectors == [[1, 0], [0, 1]]
        assert all(v.space == "a" * 32 for v in vectors)
    finally:
        embedder.client.close()


def test_sdk_failure_is_single_attempt_and_private():
    calls = []

    def handle(request):
        calls.append(1)
        raise httpx.ReadTimeout("synthetic private text")

    embedder = make_embedder(handle)
    try:
        with pytest.raises(ValueError, match=r"^embedding_request_failed$") as error:
            embedder.embed(["Секретная реплика"])
        assert "synthetic private text" not in str(error.value)
        assert calls == [1]
    finally:
        embedder.client.close()


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"vector_sync": "failed", "embedding": [1, 0]},
        {"vector_sync": "success", "embedding": []},
        {"vector_sync": "success", "embedding": [1, 0]},
    ],
)
def test_missing_index_is_not_a_memory_write_receipt(monkeypatch, metadata):
    monkeypatch.setenv("MOS_MULTIPROVIDER_ENABLED", "true")

    class Store:
        def get_node(self, id, *, user_name):
            assert user_name == "synthetic"
            return {"metadata": metadata}

    assert indexed_results(Store(), [{"memory_id": "x", "cube_id": "synthetic"}]) is None
