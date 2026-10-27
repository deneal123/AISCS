"""Native GigaChat image transport, using the real SDK and a local HTTP fixture."""

import asyncio
import base64
import json
import logging
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI, InternalServerError
from PIL import Image

from service.domain.client.calls.streaming import _stream_one_provider
from service.domain.client.protocol import ProviderProtocolError, ProviderRoundState
from service.domain.client.providers.gigachat import adapter as gigachat
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.execution.model import invoke_model_call
from service.domain.usage.ledger import UsageKind


def image_url():
    output = BytesIO()
    Image.new("RGB", (24, 24), "white").save(output, "PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def messages(count=2):
    content = [{"type": "text", "text": "Inspect the supplied pages."}]
    for number in range(count):
        content.extend(
            [
                {"type": "text", "text": f"Page {number + 1}."},
                {"type": "image_url", "image_url": {"url": image_url()}},
            ]
        )
    return [{"role": "user", "content": content}]


def response():
    return {
        "id": "fixture-call",
        "object": "chat.completion",
        "created": 0,
        "model": "GigaChat-2-Pro",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
    }


@pytest.mark.asyncio
async def test_native_image_upload_message_split_and_cleanup_preserve_usage():
    paths, uploads, bodies = [], [], []

    async def handler(request):
        paths.append((request.method, request.url.path))
        if request.url.path == "/v1/files":
            uploads.append(await request.aread())
            assert b'name="purpose"' in uploads[-1] and b"general" in uploads[-1]
            return httpx.Response(200, json={"id": str(uuid4())})
        if request.url.path.endswith("/delete"):
            return httpx.Response(200, json={"deleted": True})
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response())

    original = messages()
    before = json.dumps(original)
    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        result = await gigachat.create_chat_completion(
            original,
            "GigaChat-2-Pro",
            client=client,
        )
    assert len(uploads) == 2
    sent = bodies[0]["messages"]
    assert len(sent) == 2
    assert [item["content"].splitlines()[-1] for item in sent] == ["Page 1.", "Page 2."]
    assert all(len(item["attachments"]) == 1 for item in sent)
    assert "image_url" not in json.dumps(sent) and "base64" not in json.dumps(sent)
    assert sum(path.endswith("/delete") for _, path in paths) == 2
    assert all(method == "POST" for method, _ in paths)
    assert result.usage.total_tokens == 22
    assert json.dumps(original) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["url", "base64", "mime", "bytes", "limit", "role"])
async def test_invalid_image_never_uploads_or_calls_model(fault):
    original = messages(11 if fault == "limit" else 1)
    block = original[0]["content"][-1]
    if fault == "url":
        block["image_url"]["url"] = "http://127.0.0.1/private-marker"
    elif fault == "base64":
        block["image_url"]["url"] = "data:image/png;base64,not-base64!"
    elif fault == "mime":
        block["image_url"]["url"] = image_url().replace("image/png", "image/svg+xml")
    elif fault == "bytes":
        block["image_url"]["url"] = "data:image/png;base64,cHJpdmF0ZS1tYXJrZXI="
    elif fault == "role":
        original[0]["role"] = "system"
    called = []

    async def handler(request):
        called.append(request.url.path)
        return httpx.Response(200, json=response())

    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        with pytest.raises(ProviderProtocolError) as error:
            await gigachat.create_chat_completion(original, "GigaChat-2-Pro", client=client)
    assert error.value.reason_code == "payload"
    assert "private-marker" not in str(error.value)
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_early", [False, True])
async def test_stream_keeps_files_until_close_then_deletes_them(stop_early):
    paths = []
    identity = str(uuid4())

    async def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": identity})
        if request.url.path.endswith("/delete"):
            return httpx.Response(200, json={"deleted": True})
        assert json.loads(request.content)["messages"][0]["attachments"] == [identity]
        chunk = {
            "id": "fixture",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "GigaChat-2-Pro",
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
        }
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    state = ProviderRoundState()
    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        stream = _stream_one_provider(
            client,
            "gigachat",
            messages(1),
            "GigaChat-2-Pro",
            temperature=0,
            max_tokens=10,
            round_state=state,
            include_usage=False,
        )
        assert await anext(stream) == "ok"
        assert not any(path.endswith("/delete") for path in paths)
        if not stop_early:
            assert [piece async for piece in stream] == []
        await asyncio.create_task(stream.aclose())
    assert sum(path.endswith("/delete") for path in paths) == 1
    assert state.total == 22


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["upload", "model", "cleanup", "cancel"])
async def test_failure_and_cancellation_clean_known_uploads_without_replaying_model(fault, caplog):
    identities, deleted, model_calls = [], [], []
    entered = asyncio.Event()

    async def handler(request):
        if request.url.path == "/v1/files":
            if fault == "upload" and identities:
                return httpx.Response(503, json={"private": "provider-body-marker"})
            identity = str(uuid4())
            identities.append(identity)
            return httpx.Response(200, json={"id": identity})
        if request.url.path.endswith("/delete"):
            deleted.append(request.url.path.split("/")[-2])
            return httpx.Response(
                503 if fault == "cleanup" else 200, json={"private": "cleanup-body-marker"}
            )
        model_calls.append(1)
        if fault == "cancel":
            entered.set()
            await asyncio.Event().wait()
        if fault == "model":
            return httpx.Response(503, json={"private": "provider-body-marker"})
        return httpx.Response(200, json=response())

    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        task = asyncio.create_task(
            gigachat.create_chat_completion(
                messages(),
                "GigaChat-2-Pro",
                client=client,
            )
        )
        if fault == "cancel":
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif fault == "cleanup":
            assert (await task).usage.total_tokens == 22
        else:
            with pytest.raises(ProviderProtocolError if fault == "upload" else InternalServerError):
                await task
    assert deleted == identities
    assert len(model_calls) == (0 if fault == "upload" else 1)
    assert "cleanup-body-marker" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["upload", "cleanup"])
async def test_cancel_during_upload_or_completed_cleanup_preserves_owned_files_and_usage(stage):
    entered, release = asyncio.Event(), asyncio.Event()
    identity = str(uuid4())
    deleted = []

    async def handler(request):
        if request.url.path == "/v1/files":
            if stage == "upload":
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"id": identity})
        if request.url.path.endswith("/delete"):
            if stage == "cleanup":
                entered.set()
                await release.wait()
            deleted.append(identity)
            return httpx.Response(200, json={"deleted": True})
        return httpx.Response(200, json=response())

    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        with use_run_execution(PrivateRunResources()) as execution:
            task = asyncio.create_task(
                invoke_model_call(
                    gigachat.create_chat_completion,
                    messages=messages(1),
                    model="GigaChat-2-Pro",
                    kind=UsageKind.DOCUMENT_VISUAL_AUDIT,
                    provider_name="gigachat",
                    execution=execution,
                    client=client,
                )
            )
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            release.set()
            if stage == "cleanup":
                assert (await task).usage.total == 22
                receipts = execution.usage.receipts
                assert len(receipts) == 1
                assert receipts[0].provider == "gigachat"
                assert receipts[0].model == "GigaChat-2-Pro"
                assert receipts[0].kind == UsageKind.DOCUMENT_VISUAL_AUDIT
                assert not receipts[0].estimated
            else:
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert not execution.usage.receipts
    assert deleted == [identity]


@pytest.mark.asyncio
async def test_image_sdk_debug_logging_does_not_expose_payload_ids_or_provider_body(caplog):
    caplog.set_level(logging.DEBUG)
    identity = str(uuid4())
    original = messages(1)
    original[0]["content"][0]["text"] = "private-document-marker"

    async def handler(request):
        if request.url.path == "/v1/files":
            return httpx.Response(200, json={"id": identity})
        if request.url.path.endswith("/delete"):
            return httpx.Response(503, json={"private": "private-provider-body-marker"})
        return httpx.Response(200, json=response())

    async with AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        assert (
            await gigachat.create_chat_completion(
                original,
                "GigaChat-2-Pro",
                client=client,
            )
        ).usage.total_tokens == 22
    assert "private-document-marker" not in caplog.text
    assert "private-provider-body-marker" not in caplog.text
    assert identity not in caplog.text
    assert "https://fixture.invalid" not in caplog.text
    assert "provider_image_cleanup provider=gigachat status=failed" in caplog.text
    logging.getLogger("httpx").debug("outside-image-scope")
    assert "outside-image-scope" in caplog.text
