"""Настоящий SDK и admission; заменён только HTTP-транспорт внешнего провайдера."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, AsyncOpenAI

from service.domain.client.models.catalog import (
    ModelCatalogSource,
    ModelCatalogStatus,
    ProviderModelCatalog,
    ProviderModelRecord,
)
from service.domain.client.providers.management.admission import (
    RunProviderAdmission,
    RunProviderSnapshot,
)
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.tools.image_gen import generate_image_b64
from service.shared.harness_protocol import HarnessFailure

FLUX = "black-forest-labs/flux-3-image"
GEMINI = "google/gemini-2.5-flash-image"
ENCODED = "aGVsbG8="


@pytest.fixture(autouse=True)
def enable_image_api_protocol_fixture(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "image_only_api_enabled", True)


def admission(client, provider, *records):
    catalog = ProviderModelCatalog(
        provider=provider,
        models=tuple(item.model_id for item in records),
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
            owner_index={item.model_id: provider for item in records},
            provider_order=(provider,),
            active_provider=provider,
            configuration_generation="image-protocol-test",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["routerai", "openrouter"])
@pytest.mark.parametrize("reference", [None, "data:image/png;base64,cmVm"])
async def test_image_only_models_use_images_api_once_and_preserve_reference(provider, reference):
    requests = []

    def transport(request):
        requests.append(request)
        assert request.url.path == "/v1/images"
        body = json.loads(request.content)
        assert body["model"] == FLUX and body["prompt"] == "Котик" and body["n"] == 1
        assert "messages" not in body and "modalities" not in body
        if reference:
            assert body["input_references"] == [
                {"type": "image_url", "image_url": {"url": reference}}
            ]
        else:
            assert "input_references" not in body
        return httpx.Response(
            200, json={"created": 0, "data": [{"b64_json": ENCODED}], "usage": {"cost": 1}}
        )

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, provider, ProviderModelRecord(FLUX, frozenset({"image_output"}))
            )
            assert (
                await generate_image_b64(FLUX, "Котик", execution, reference_image_url=reference)
                == ENCODED
            )
            assert len(requests) == 1 and len(execution.usage.receipts) == 1
            assert execution.usage.receipts[0].model == FLUX
            assert execution.usage.receipts[0].provider == provider
            assert execution.usage.receipts[0].billable
            assert execution.usage.receipts[0].estimated
            assert execution.usage.receipts[0].total == 1024


@pytest.mark.asyncio
async def test_chat_image_model_keeps_multimodal_protocol_and_actual_usage():
    def transport(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["modalities"] == ["image", "text"]
        assert body["messages"] == [{"role": "user", "content": "Котик"}]
        return httpx.Response(
            200,
            json={
                "id": "image-chat",
                "object": "chat.completion",
                "created": 0,
                "model": GEMINI,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "images": [{"image_url": {"url": "data:image/png;base64," + ENCODED}}],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 7, "completion_tokens": 20, "total_tokens": 27},
            },
        )

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, "routerai", ProviderModelRecord(GEMINI, frozenset({"chat", "image_output"}))
            )
            assert await generate_image_b64(GEMINI, "Котик", execution) == ENCODED
            assert execution.usage.as_token_usage()["total"] == 27


@pytest.mark.asyncio
async def test_missing_image_is_not_billed_and_does_not_switch_to_chat_endpoint():
    requests = []

    def transport(request):
        requests.append(request)
        assert request.url.path == "/v1/images"
        return httpx.Response(200, json={"created": 0, "data": [], "usage": {"cost": 1}})

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, "routerai", ProviderModelRecord(FLUX, frozenset({"image_output"}))
            )
            assert await generate_image_b64(FLUX, "Котик", execution) == ""
            assert len(requests) == 2
            assert all(not receipt.billable for receipt in execution.usage.receipts)


@pytest.mark.asyncio
async def test_unknown_http_ack_is_not_retried_or_rerouted():
    requests = []

    def transport(request):
        requests.append(request)
        raise httpx.ReadTimeout("synthetic unknown acknowledgement")

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, "routerai", ProviderModelRecord(FLUX, frozenset({"image_output"}))
            )
            with pytest.raises(APITimeoutError):
                await generate_image_b64(FLUX, "Котик", execution)
            assert len(requests) == 1


@pytest.mark.asyncio
async def test_direct_image_transport_cannot_bypass_durable_harness_grants():
    from service.domain.client.providers.images.transport import create_image

    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = SimpleNamespace(failure="")
        with pytest.raises(HarnessFailure, match="unsupported_adapter"):
            await create_image(None, dedicated=True, model=FLUX, messages=[], extra_body={})


@pytest.mark.asyncio
async def test_disabled_image_billing_blocks_before_any_http_or_ledger_receipt(monkeypatch):
    from service.domain.client.providers.images.transport import ImageBillingUnavailable
    from service.settings import config

    monkeypatch.setattr(config.agents, "image_only_api_enabled", False)
    requests = []

    def transport(request):
        requests.append(request)
        raise AssertionError("Неопределённый тариф не разрешает платный запрос")

    async with AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, "routerai", ProviderModelRecord(FLUX, frozenset({"image_output"}))
            )
            with pytest.raises(ImageBillingUnavailable):
                await generate_image_b64(FLUX, "Котик", execution)
            assert not requests and not execution.usage.receipts


@pytest.mark.asyncio
async def test_image_billing_block_does_not_start_a_paid_prompt_fallback(monkeypatch):
    from unittest.mock import AsyncMock

    from service.domain.client.providers.images.transport import ImageBillingUnavailable
    from service.domain.subagents.image_generation import ImageGenerationAgent
    from service.events import EventType

    agent = ImageGenerationAgent({})
    monkeypatch.setattr("service.domain.client.list_qualified_models", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "service.domain.subagents.context_query.build_standalone_query",
        AsyncMock(return_value="Котик"),
    )
    monkeypatch.setattr(
        agent,
        "evaluate_input_safety",
        AsyncMock(return_value={"sensitive": False, "blocked": False}),
    )
    monkeypatch.setattr(
        agent, "_generate_image_b64", AsyncMock(side_effect=ImageBillingUnavailable())
    )
    fallback = AsyncMock(side_effect=AssertionError("Отказ по цене не требует платного промпта"))
    monkeypatch.setattr(agent, "_build_prompt_fallback", fallback)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.provider_admission = admission(
            object(), "routerai", ProviderModelRecord(FLUX, frozenset({"image_output"}))
        )
        events = [event async for event in agent.process("Нарисуй котика", None)]
        assert not execution.usage.receipts
    assert any(
        event.type == EventType.STREAM_CHUNK and "не выполнялся" in str(event.data)
        for event in events
    )
    fallback.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("records", "expected"),
    [
        (
            (
                ProviderModelRecord(FLUX, frozenset({"image_output"})),
                ProviderModelRecord(GEMINI, frozenset({"chat", "image_output"})),
            ),
            GEMINI,
        ),
        ((ProviderModelRecord(FLUX, frozenset({"image_output"})),), FLUX),
        ((ProviderModelRecord("artist-v1", frozenset({"image_output"})),), "artist-v1"),
    ],
)
async def test_agent_admission_prefers_supported_generator_not_catalog_order(
    monkeypatch, records, expected
):
    from service.domain.subagents.image_generation import ImageGenerationAgent
    from service.events import EventType

    async def models():
        return ["text-model"]

    async def query(user_input, *_args, **_kwargs):
        return user_input

    async def safe(_text):
        return {"sensitive": False, "blocked": False}

    async def generate(model, *_args, **_kwargs):
        assert model == expected
        return ENCODED

    monkeypatch.setattr("service.domain.client.list_qualified_models", models)
    monkeypatch.setattr("service.domain.subagents.context_query.build_standalone_query", query)
    agent = ImageGenerationAgent({})
    monkeypatch.setattr(agent, "evaluate_input_safety", safe)
    monkeypatch.setattr(agent, "_generate_image_b64", generate)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.provider_admission = admission(object(), "routerai", *records)
        events = [event async for event in agent.process("Нарисуй котика", None)]
    assert any(
        event.type == EventType.STREAM_CHUNK and (event.metadata or {}).get("model") == expected
        for event in events
    )


@pytest.mark.parametrize(
    "url", ["https://example.invalid/a,b", "data:text/plain;base64," + ENCODED, "not-an-image"]
)
def test_response_parser_does_not_treat_arbitrary_urls_as_image_receipts(url):
    from service.domain.client.providers.images.responses import image_base64

    assert image_base64({"choices": [{"message": {"images": [{"image_url": url}]}}]}) == ""


def test_chat_parser_preserves_sdk_dump_compatibility():
    from service.domain.client.providers.images.responses import image_base64

    class Message:
        def model_dump(self):
            return {"images": [{"image_url": "data:image/png;base64," + ENCODED}]}

    assert image_base64(SimpleNamespace(choices=[SimpleNamespace(message=Message())])) == ENCODED


def test_image_response_preserves_actual_input_output_tokens():
    from service.domain.client.providers.images.responses import dedicated_response

    response = dedicated_response({"data": [], "usage": {"input_tokens": 7, "output_tokens": 23}})
    assert response.usage.prompt_tokens == 7
    assert response.usage.completion_tokens == 23


@pytest.mark.asyncio
async def test_dedicated_sdk_logging_does_not_disclose_prompt_or_base64(caplog):
    import logging

    marker = "private-cat-instruction-409"
    encoded = "private-image-bytes-803"
    caplog.set_level(logging.DEBUG)

    def transport(_request):
        return httpx.Response(200, json={"created": 0, "data": [{"b64_json": encoded}]})

    async with AsyncOpenAI(
        api_key="test-key",
        base_url="https://fixture/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            execution.provider_admission = admission(
                client, "routerai", ProviderModelRecord(FLUX, frozenset({"image_output"}))
            )
            assert await generate_image_b64(FLUX, marker, execution) == encoded
    assert marker not in caplog.text
    assert encoded not in caplog.text
    assert "test-key" not in caplog.text
