"""Реальный OpenAI SDK должен сохранить нативный usage GigaChat на всём batch."""

import httpx
import pytest
from openai import AsyncOpenAI

from service.domain.client.providers.embedding_responses import normalize


@pytest.mark.asyncio
async def test_native_item_usage_is_aggregated_once_without_changing_vectors():
    calls = []

    def respond(request):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "Embeddings",
                "data": [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [0.1, 0.2],
                        "usage": {"prompt_tokens": 7},
                    },
                    {
                        "object": "embedding",
                        "index": 1,
                        "embedding": [0.3, 0.4],
                        "usage": {"prompt_tokens": 11},
                    },
                ],
            },
        )

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="http://synthetic/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        response = await sdk.embeddings.create(
            model="Embeddings", input=["Первое", "Второе"], encoding_format="float"
        )
    result = normalize("gigachat", response)
    assert result.usage.prompt_tokens == result.usage.total_tokens == 18
    assert result.data[0].embedding == [0.1, 0.2]
    assert normalize("gigachat", result) is result
    assert calls == [1]
