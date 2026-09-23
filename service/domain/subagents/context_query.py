"""Strict resolution of a follow-up into one standalone research query."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from service.domain.client import create_chat_completion
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.usage_ledger import UsageKind

logger = logging.getLogger(__name__)

_CONDENSE_SYSTEM = (
    "Перепиши последний запрос пользователя в один самостоятельный поисковый запрос. "
    "Раскрой местоименные ссылки по диалогу. Убирай обращение к ассистенту и команду: "
    "нужен ПРЕДМЕТ запроса. Сохраняй все уточнения предмета, имена, точные цитаты, "
    "даты, диапазоны, отрицания и ограничения. "
    'Не объясняй решение. Верни строгий JSON только вида {"query": "..."}.'
)
_DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}(?:[-–—/.](?:0?[1-9]|1[0-2]))?(?:[-–—/.](?:0?[1-9]|[12]\d|3[01]))?\b"
)
_QUOTE_RE = re.compile(r"[«\"„](.*?)[»\"“]", re.DOTALL)
_CAPITALIZED_RE = re.compile(r"(?<![.!?]\s)\b[A-ZА-ЯЁ][\w.-]{2,}(?:\s+[A-ZА-ЯЁ][\w.-]{2,}){0,3}")
_NEGATIONS = frozenset({"не", "без", "кроме", "исключая", "not", "without", "except"})
_COMMAND_PREFIX_RE = re.compile(
    r"^\s*(?:пожалуйста[, ]+)?(?:найди|поищи|расскажи|объясни|изучи|проведи\s+"
    r"(?:глубокий\s+)?поиск(?:\s+на\s+тему)?|research|find|search|explain)\b[: ,—-]*",
    re.IGNORECASE,
)


class QueryResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNCHANGED = "unchanged"
    FALLBACK = "fallback"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class QueryConstraints:
    quoted: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    names: tuple[str, ...] = ()
    negations: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.quoted) + len(self.dates) + len(self.names) + len(self.negations)


@dataclass(frozen=True, slots=True)
class QueryResolution:
    query: str
    status: QueryResolutionStatus
    constraints: QueryConstraints
    usage_receipt_id: str | None = None

    def bounded_metadata(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "constraint_count": self.constraints.count,
            "query_chars": len(self.query),
            "usage_recorded": bool(self.usage_receipt_id),
        }


def _persona_condense_system() -> str:
    from service.domain import persona

    return persona.current().wrap(_CONDENSE_SYSTEM, "search.query")


def _safe_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    return re.sub(r"\s+", " ", text)[:limit].strip()


def extract_constraints(text: str) -> QueryConstraints:
    value = _safe_text(text)
    lower_words = {word.lower() for word in re.findall(r"\b[\w-]+\b", value)}
    return QueryConstraints(
        quoted=tuple(dict.fromkeys(_safe_text(item, 240) for item in _QUOTE_RE.findall(value))),
        dates=tuple(dict.fromkeys(_DATE_RE.findall(value))),
        names=tuple(dict.fromkeys(_CAPITALIZED_RE.findall(value))),
        negations=tuple(sorted(_NEGATIONS.intersection(lower_words))),
    )


def _constraint_is_present(item: str, query: str) -> bool:
    normalized = re.sub(r"\s+", " ", item).casefold()
    return normalized in re.sub(r"\s+", " ", query).casefold()


def preserves_constraints(query: str, constraints: QueryConstraints) -> bool:
    required = (*constraints.quoted, *constraints.dates, *constraints.names, *constraints.negations)
    return all(_constraint_is_present(item, query) for item in required)


def _parse_resolution(raw: str) -> str | None:
    value = raw.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"query"}:
        return None
    query = _safe_text(parsed.get("query"), 2000)
    if not query or "\n" in query:
        return None
    return query


def _history_excerpt(context: Any) -> str:
    history = list(getattr(context, "history_messages", None) or [])[-6:]
    lines: list[str] = []
    total = 0
    for message in history:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = _safe_text(message.get("content"), 600)
        if not content:
            continue
        line = f"{role}: {content}"
        if total + len(line) > 2800:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def _fallback_query(user_input: str) -> str:
    original = _safe_text(user_input, 2000)
    stripped = _COMMAND_PREFIX_RE.sub("", original).strip()
    return stripped or original


async def resolve_query(
    user_input: str,
    context: Any,
    model: str | None,
    *,
    execution: RunExecutionContext | None = None,
) -> QueryResolution:
    """Resolve with strict parsing and deterministic preservation checks."""

    execution = require_execution(execution)
    original = _safe_text(user_input, 2000)
    fallback = _fallback_query(original)
    constraints = extract_constraints(original)
    history = _history_excerpt(context)
    if not history or not model:
        return QueryResolution(fallback, QueryResolutionStatus.UNCHANGED, constraints)
    try:
        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.QUERY_RESOLUTION,
            execution=execution,
            messages=[
                {"role": "system", "content": _persona_condense_system()},
                {
                    "role": "user",
                    "content": (f"Диалог:\n{history}\n\nПоследний запрос:\n{original}\n\nJSON:"),
                },
            ],
            model=model,
            temperature=0.0,
            max_tokens=120,
        )
    except Exception:  # noqa: BLE001
        logger.debug("query resolution failed with bounded code=unavailable")
        return QueryResolution(original, QueryResolutionStatus.FALLBACK, constraints)
    response = result.response
    receipt_id = result.usage.receipt_id
    resolved = _parse_resolution(first_message_content(response))
    if not resolved or not preserves_constraints(resolved, constraints):
        return QueryResolution(
            original,
            QueryResolutionStatus.INVALID,
            constraints,
            receipt_id,
        )
    return QueryResolution(
        resolved,
        QueryResolutionStatus.RESOLVED,
        constraints,
        receipt_id,
    )


async def build_standalone_query(
    user_input, context, model, *, execution: RunExecutionContext | None = None
) -> str:
    """Compatibility facade returning only the standalone query string."""

    resolution = await resolve_query(
        user_input,
        context,
        model,
        execution=execution,
    )
    return resolution.query


__all__ = [
    "QueryConstraints",
    "QueryResolution",
    "QueryResolutionStatus",
    "build_standalone_query",
    "extract_constraints",
    "preserves_constraints",
    "resolve_query",
]
