"""The live fault injector loses only an ACK, never a real commit or executor call."""

import json

import pytest

from scripts.harness.live.lost_ack import LostAck, LostAckMiddleware


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,payload",
    [
        ("checkpoint", {"opcode": "checkpoint"}),
        (
            "file_receipt",
            {"opcode": "effect_receipt", "effect_result": {"evidence": [{"kind": "file"}]}},
        ),
        ("paid_receipt", {"opcode": "call_receipt", "receipt": {"prompt": 128}}),
        ("question_cost", {"decision": "accept"}),
    ],
)
async def test_fault_occurs_once_only_after_successful_transaction(mode, payload):
    committed = []

    async def real_handler(scope, receive, send):
        message = await receive()
        assert json.loads(message["body"]) == payload
        committed.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"committed":true}'})

    fault = LostAck(mode)
    middleware = LostAckMiddleware(real_handler, fault)
    for expected in [503, 200]:
        observed = []

        async def receive():
            return {"type": "http.request", "body": json.dumps(payload).encode()}

        async def send(message, output=observed):
            assert committed
            output.append(message)

        path = (
            "/internal/harness/v1/exchange"
            if mode != "question_cost"
            else (
                "/api/chats/00000000-0000-0000-0000-000000000001/runs/"
                "00000000-0000-0000-0000-000000000002/questions/"
                "00000000-0000-0000-0000-000000000003/cost"
            )
        )
        await middleware({"type": "http", "path": path, "method": "POST"}, receive, send)
        assert observed[0]["status"] == expected
        if expected == 503:
            assert json.loads(observed[1]["body"]) == {
                "detail": {
                    "code": (
                        "human_question_status_unknown"
                        if mode == "question_cost"
                        else "checkpoint_unavailable"
                    )
                }
            }
    assert fault.count == 1 and len(committed) == 2


@pytest.mark.parametrize(
    "mode,payload",
    [
        (
            "file_receipt",
            {"opcode": "effect_receipt", "effect_result": {"evidence": [{"kind": "read"}]}},
        ),
        ("paid_receipt", {"opcode": "call_receipt", "receipt": {"prompt": 0}}),
        ("checkpoint", {"opcode": "dispatch_effect"}),
        ("question_cost", {"decision": "decline"}),
    ],
)
def test_non_target_ack_is_not_lost(mode, payload):
    assert not LostAck(mode).matches(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method",
    [
        ("/internal/harness/v1/exchange", "POST"),
        ("/api/chats/question/cost", "POST"),
        (
            "/api/chats/00000000-0000-0000-0000-000000000001/runs/"
            "00000000-0000-0000-0000-000000000002/questions/"
            "00000000-0000-0000-0000-000000000003/cost",
            "GET",
        ),
    ],
)
async def test_question_cost_fault_does_not_intercept_other_paths_or_reads(path, method):
    async def handler(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    fault = LostAck("question_cost")
    observed = []

    async def receive():
        return {"type": "http.request", "body": b'{"decision":"accept"}'}

    async def send(message):
        observed.append(message)

    await LostAckMiddleware(handler, fault)(
        {"type": "http", "path": path, "method": method}, receive, send
    )
    assert observed[0]["status"] == 200 and fault.count == 0
