"""Closed question/answer codec; private continuation never enters the public view."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5


class HumanQuestionError(RuntimeError):
    def __init__(self, code: str = "human_question_invalid") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class QuestionRefusal:
    """A committed business refusal, not a database exception/unknown commit."""

    code: str


def _plain(value: Any, limit: int) -> str:
    if (
        type(value) is not str
        or not 0 < len(value) <= limit
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise HumanQuestionError()
    return value


def _json(value: Any, limit: int) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if len(encoded.encode("utf-8")) > limit:
            raise ValueError
        return encoded
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise HumanQuestionError() from None


@dataclass(frozen=True, slots=True)
class QuestionChoice:
    id: str
    label: str

    def __post_init__(self) -> None:
        _plain(self.label, 120)
        if re.fullmatch(r"[a-z][a-z0-9_-]*", _plain(self.id, 32)) is None:
            raise HumanQuestionError()

    @classmethod
    def parse(cls, raw: Any) -> QuestionChoice:
        if type(raw) is not dict or set(raw) != {"id", "label"}:
            raise HumanQuestionError()
        key = _plain(raw["id"], 32)
        if re.fullmatch(r"[a-z][a-z0-9_-]*", key) is None:
            raise HumanQuestionError()
        return cls(key, _plain(raw["label"], 120))


@dataclass(frozen=True, slots=True)
class QuestionPrompt:
    prompt: str
    choices: tuple[QuestionChoice, ...]

    def __post_init__(self) -> None:
        _plain(self.prompt, 1000)
        if (
            type(self.choices) is not tuple
            or len(self.choices) not in {0, 2, 3}
            or not all(isinstance(item, QuestionChoice) for item in self.choices)
            or len({item.id for item in self.choices}) != len(self.choices)
        ):
            raise HumanQuestionError()

    @classmethod
    def parse(cls, raw: Any) -> QuestionPrompt:
        if type(raw) is not dict or set(raw) != {"prompt", "choices"}:
            raise HumanQuestionError()
        rows = raw["choices"]
        if type(rows) is not list or len(rows) not in {0, 2, 3}:
            raise HumanQuestionError()
        choices = tuple(QuestionChoice.parse(item) for item in rows)
        if len({item.id for item in choices}) != len(choices):
            raise HumanQuestionError()
        return cls(_plain(raw["prompt"], 1000), choices)

    def payload(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "choices": [{"id": row.id, "label": row.label} for row in self.choices],
        }


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    choice_id: str | None
    text: str | None = field(repr=False)

    @classmethod
    def parse(cls, raw: Any, prompt: QuestionPrompt) -> QuestionAnswer:
        if type(raw) is not dict or set(raw) != {"choice_id", "text"}:
            raise HumanQuestionError()
        choice = raw["choice_id"]
        if choice is not None and (
            type(choice) is not str or choice not in {item.id for item in prompt.choices}
        ):
            raise HumanQuestionError()
        value = raw["text"]
        if value is not None and (
            type(value) is not str
            or not value.strip()
            or len(value) > 4000
            or any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in value)
        ):
            raise HumanQuestionError()
        if choice is None and value is None:
            raise HumanQuestionError()
        return cls(choice, value)

    def payload(self) -> dict[str, Any]:
        return {"choice_id": self.choice_id, "text": self.text}


@dataclass(frozen=True, slots=True)
class QuestionScope:
    user_id: UUID
    thread_id: UUID
    source_job_id: UUID

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, UUID) and value.int
            for value in (self.user_id, self.thread_id, self.source_job_id)
        ):
            raise HumanQuestionError()

    def params(self) -> dict[str, UUID]:
        return {
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "source_job_id": self.source_job_id,
        }


@dataclass(frozen=True, slots=True)
class QuestionPause:
    scope: QuestionScope
    question_id: UUID
    execution_attempt_id: UUID = field(repr=False)
    surface: Literal["ide", "pdf"]
    project_id: UUID
    revision: str
    prompt: QuestionPrompt
    expires_at: float
    continuation_json: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope, QuestionScope)
            or not isinstance(self.question_id, UUID)
            or not self.question_id.int
            or not isinstance(self.execution_attempt_id, UUID)
            or not self.execution_attempt_id.int
            or self.surface not in {"ide", "pdf"}
            or not isinstance(self.project_id, UUID)
            or not self.project_id.int
            or not isinstance(self.prompt, QuestionPrompt)
            or type(self.expires_at) not in {int, float}
            or not math.isfinite(self.expires_at)
            or not 0 < self.expires_at < 253402300800
        ):
            raise HumanQuestionError()
        _plain(self.revision, 128)
        try:
            value = json.loads(self.continuation_json)
            if type(value) is not dict or _json(value, 1024 * 1024) != self.continuation_json:
                raise ValueError
        except (ValueError, TypeError, RecursionError):
            raise HumanQuestionError() from None
        # Constructors cannot bypass the same validation as wire DTOs.
        QuestionPrompt.parse(self.prompt.payload())

    @property
    def resume_job_id(self) -> UUID:
        return uuid5(self.question_id, "gpthub:human-question:resume:v1")

    def params(self) -> dict[str, Any]:
        body = {
            "surface": self.surface,
            "project_id": str(self.project_id),
            "revision": self.revision,
            "prompt": self.prompt.payload(),
            "expires_at": self.expires_at,
            "continuation": json.loads(self.continuation_json),
        }
        digest = hashlib.sha256(_json(body, 2 * 1024 * 1024).encode()).hexdigest()
        return {
            **self.scope.params(),
            "question_id": self.question_id,
            "attempt_id": str(self.execution_attempt_id),
            "surface": self.surface,
            "project_id": self.project_id,
            "revision": self.revision,
            "prompt": _json(self.prompt.payload(), 8192),
            "expires_at": self.expires_at,
            "continuation": self.continuation_json,
            "digest": digest,
        }


def freeze_continuation(value: dict[str, Any]) -> str:
    """Freeze trusted server context; it must never be returned by a public route."""
    if type(value) is not dict:
        raise HumanQuestionError()
    return _json(value, 1024 * 1024)


def _validate_message_content(message: dict, role: str) -> None:
    allowed = {"role", "content", "tool_calls"} if role == "assistant" else {"role", "content"}
    if (
        not {"role", "content"} <= set(message)
        or set(message) - allowed
        or (type(message["content"]) is not str and message["content"] is not None)
        or (message["content"] is None and role != "assistant")
    ):
        raise HumanQuestionError()


def _validate_transcript_calls(calls: Any, pending: set[str]) -> None:
    if type(calls) is not list:
        raise HumanQuestionError()
    for call in calls:
        if (
            type(call) is not dict
            or set(call) != {"id", "type", "function"}
            or call["type"] != "function"
            or type(call["function"]) is not dict
            or set(call["function"]) != {"name", "arguments"}
            or type(call["function"]["arguments"]) is not str
        ):
            raise HumanQuestionError()
        call_id = _plain(call["id"], 160)
        _plain(call["function"]["name"], 128)
        if call_id in pending:
            raise HumanQuestionError()
        pending.add(call_id)


def freeze_question_continuation(raw: Any, prompt: QuestionPrompt) -> str:
    """Freeze a complete text/tool transcript, never a capability-bearing run object.

    Only the last, lone question tool awaits a human. Earlier completed tool
    results stay in order; resuming never dispatches those calls again.
    """
    if type(raw) is not dict or set(raw) != {"model", "messages", "tool_call_id"}:
        raise HumanQuestionError()
    _plain(raw["model"], 128)
    question_call = _plain(raw["tool_call_id"], 160)
    messages = raw["messages"]
    if type(messages) is not list or not 2 <= len(messages) <= 512:
        raise HumanQuestionError()
    pending: set[str] = set()
    for message in messages:
        if type(message) is not dict:
            raise HumanQuestionError()
        role = message.get("role")
        if role == "tool":
            if (
                set(message) != {"role", "content", "tool_call_id"}
                or type(message["tool_call_id"]) is not str
                or message["tool_call_id"] not in pending
                or type(message["content"]) is not str
            ):
                raise HumanQuestionError()
            pending.remove(message["tool_call_id"])
            continue
        if pending or type(role) is not str or role not in {"system", "user", "assistant"}:
            raise HumanQuestionError()
        _validate_message_content(message, role)
        _validate_transcript_calls(message.get("tool_calls", []), pending)
    if (
        pending
        or messages[-1].get("role") != "tool"
        or messages[-1]["tool_call_id"] != question_call
    ):
        raise HumanQuestionError()
    calls = messages[-2].get("tool_calls", [])
    if (
        messages[-2].get("role") != "assistant"
        or len(calls) != 1
        or calls[0]["id"] != question_call
        or calls[0]["function"]["name"] != "ask_user_question"
    ):
        raise HumanQuestionError()
    try:
        arguments = json.loads(calls[0]["function"]["arguments"])
        sentinel = json.loads(messages[-1]["content"])
        if (
            QuestionPrompt.parse(arguments) != prompt
            or type(sentinel) is not dict
            or set(sentinel) != {"awaiting_user"}
            or sentinel["awaiting_user"] is not True
        ):
            raise HumanQuestionError()
    except (ValueError, TypeError, RecursionError):
        raise HumanQuestionError() from None
    return freeze_continuation(raw)


def resume_question_continuation(raw: Any, prompt: QuestionPrompt, answer: Any) -> dict[str, Any]:
    """Replace only the pending tool result; no synthetic second user message."""
    parsed = QuestionAnswer.parse(answer, prompt)
    frozen = freeze_question_continuation(raw, prompt)
    copied = json.loads(frozen)
    copied["messages"][-1]["content"] = _json({"answer": parsed.payload()}, 32768)
    return {"model": copied["model"], "messages": copied["messages"]}


def parse_resumed_question_continuation(raw: Any) -> dict[str, Any]:
    """Validate an answered checkpoint before the next model round, without replay."""
    if type(raw) is not dict or set(raw) != {"model", "messages"}:
        raise HumanQuestionError()
    try:
        copied = json.loads(freeze_continuation(raw))
        messages = copied["messages"]
        if type(messages) is not list or len(messages) < 2:
            raise HumanQuestionError()
        call = messages[-2]["tool_calls"][0]
        prompt = QuestionPrompt.parse(json.loads(call["function"]["arguments"]))
        result = json.loads(messages[-1]["content"])
        if type(result) is not dict or set(result) != {"answer"}:
            raise HumanQuestionError()
        messages[-1]["content"] = '{"awaiting_user":true}'
        return resume_question_continuation(
            {**copied, "tool_call_id": call["id"]}, prompt, result["answer"]
        )
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise HumanQuestionError() from None


def parse_public_question(raw: Any) -> dict[str, Any]:
    """Pure, clock-independent projection for immutable message/recovery metadata."""
    expected = {
        "question_id",
        "source_job_id",
        "surface",
        "project_id",
        "prompt",
        "choices",
        "state",
        "expires_at",
        "resume_job_id",
    }
    if type(raw) is not dict or set(raw) != expected:
        raise HumanQuestionError()
    for key in ("question_id", "source_job_id", "project_id", "resume_job_id"):
        if key == "resume_job_id" and raw[key] is None:
            continue
        try:
            if type(raw[key]) is not str or str(UUID(raw[key])) != raw[key]:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise HumanQuestionError() from None
    if (
        type(raw["surface"]) is not str
        or raw["surface"] not in {"ide", "pdf"}
        or type(raw["state"]) is not str
        or raw["state"] not in {"pending", "accepted", "cancelled", "expired"}
        or (raw["state"] == "accepted") != (raw["resume_job_id"] is not None)
    ):
        raise HumanQuestionError()
    try:
        stamp = datetime.fromisoformat(raw["expires_at"])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError):
        raise HumanQuestionError() from None
    prompt = QuestionPrompt.parse({"prompt": raw["prompt"], "choices": raw["choices"]})
    return {**raw, **prompt.payload()}
