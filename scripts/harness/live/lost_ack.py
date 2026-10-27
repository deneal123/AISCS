"""Fixture-only loss of a successful HTTP ACK after the real transaction commits."""

import json
import re


class LostAck:
    def __init__(self, mode=""):
        if mode not in {
            "",
            "checkpoint",
            "file_receipt",
            "paid_receipt",
            "question_cost",
            "paid_receipt_unavailable",
            "stream_receipt_unavailable",
        }:
            raise ValueError("acceptance_unknown_ack_fault")
        self.mode, self.count = mode, 0

    def matches(self, payload):
        if not self.mode or self.count:
            return False
        if self.mode == "question_cost":
            return payload.get("decision") == "accept"
        if self.mode == "checkpoint":
            return payload.get("opcode") == "checkpoint"
        if self.mode == "file_receipt":
            return payload.get("opcode") == "effect_receipt" and any(
                item.get("kind") == "file"
                for item in (payload.get("effect_result") or {}).get("evidence", [])
            )
        if self.mode in {"paid_receipt_unavailable", "stream_receipt_unavailable"}:
            receipt = payload.get("receipt") or {}
            if (
                payload.get("opcode") != "call_receipt"
                or receipt.get("status") != "succeeded"
                or receipt.get("estimated")
                or receipt.get("prompt", 0) + receipt.get("completion", 0) <= 0
            ):
                return False
            return self.mode == "paid_receipt_unavailable" or any(
                call.get("function", {}).get("name") != "submit_task_contract"
                for call in (receipt.get("message") or {}).get("tool_calls", [])
            )
        return (
            payload.get("opcode") == "call_receipt"
            and (payload.get("receipt") or {}).get("prompt", 0) > 0
        )


class LostAckMiddleware:
    def __init__(self, app, fault):
        self.app, self.fault = app, fault

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        target = (
            bool(
                re.fullmatch(
                    r"/api/chats/[a-f0-9-]{36}/runs/[a-f0-9-]{36}/questions/[a-f0-9-]{36}/cost",
                    path,
                )
            )
            and scope.get("method") == "POST"
            if self.fault.mode == "question_cost"
            else path == "/internal/harness/v1/exchange"
        )
        if not target or not self.fault.mode:
            return await self.app(scope, receive, send)
        body = bytearray()
        drop = False

        async def observed_receive():
            message = await receive()
            body.extend(message.get("body", b""))
            return message

        async def observed_send(message):
            nonlocal drop
            if message["type"] == "http.response.start" and message["status"] == 200:
                if self.fault.matches(json.loads(body)):
                    # The handler sent success only after its actual commit. Do not
                    # replace storage/execution; lose only this success acknowledgement.
                    self.fault.count += 1
                    drop = True
                    message = {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"private, no-store"),
                        ],
                    }
            if drop and message["type"] == "http.response.body":
                if message.get("more_body"):
                    return
                message = {
                    "type": "http.response.body",
                    "body": json.dumps(
                        {
                            "detail": {
                                "code": "human_question_status_unknown"
                                if self.fault.mode == "question_cost"
                                else "checkpoint_unavailable"
                            }
                        }
                    ).encode(),
                }
            await send(message)

        await self.app(scope, observed_receive, observed_send)
