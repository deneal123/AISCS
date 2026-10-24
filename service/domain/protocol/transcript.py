"""Проверенная история native вызовов: результаты остаются ролью tool, не user."""

import json
import re

from .contracts import ProtocolFailure


def canonical_messages(messages: list) -> list[dict]:
    if not messages or len(messages) > 512:
        raise ProtocolFailure("messages_invalid")
    result, pending, seen = [], set(), set()
    for message in messages:
        if not isinstance(message, dict):
            raise ProtocolFailure("messages_invalid")
        role, content = message.get("role"), message.get("content")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ProtocolFailure("messages_invalid")
        if content is not None and not isinstance(content, str):
            raise ProtocolFailure("text_only_model")
        calls = message.get("tool_calls") or []
        if calls:
            if role != "assistant" or pending or not isinstance(calls, list):
                raise ProtocolFailure("transcript_invalid")
            rendered = []
            for call in calls:
                try:
                    identity = call["id"]
                    function = call["function"]
                    arguments = json.loads(function["arguments"])
                    if (
                        not isinstance(identity, str)
                        or not 1 <= len(identity) <= 128
                        or identity in seen
                        or call.get("type") != "function"
                        or not isinstance(arguments, dict)
                        or not isinstance(function.get("name"), str)
                        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", function["name"])
                    ):
                        raise ValueError
                    pending.add(identity)
                    seen.add(identity)
                    rendered.append(
                        {
                            "id": identity,
                            "type": "function",
                            "function": {
                                "name": function["name"],
                                "arguments": json.dumps(
                                    arguments, ensure_ascii=False, allow_nan=False
                                ),
                            },
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    raise ProtocolFailure("transcript_invalid") from None
            result.append(
                {
                    "role": role,
                    "content": content,
                    "tool_calls": rendered,
                }
            )
        elif role == "tool":
            identity = message.get("tool_call_id")
            if identity not in pending:
                raise ProtocolFailure("transcript_invalid")
            pending.remove(identity)
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": identity,
                    "content": content or "",
                }
            )
        else:
            if pending:
                raise ProtocolFailure("transcript_invalid")
            result.append({"role": role, "content": content or ""})
    if pending:
        raise ProtocolFailure("transcript_invalid")
    return result
