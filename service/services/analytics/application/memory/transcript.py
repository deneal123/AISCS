"""Bounded extraction context with unambiguous speaker boundaries.

This protects transcript structure, not the truth of model-extracted facts.
Assistant text stays available to interpret explicit user confirmations.
"""

from __future__ import annotations

import json
from typing import Any

TRANSCRIPT_LIMIT = 6000


def _quoted_prefix(content: str, limit: int) -> str:
    """Fit a closed JSON string; never split a speaker record inside an escape."""
    lower, upper = 0, min(len(content), limit)
    encoded = ""
    while lower <= upper:
        size = (lower + upper) // 2
        candidate = json.dumps(content[:size], ensure_ascii=False)
        for character, escape in (
            ("\x85", "\\u0085"),
            ("\u2028", "\\u2028"),
            ("\u2029", "\\u2029"),
        ):
            candidate = candidate.replace(character, escape)
        if len(candidate) <= limit:
            encoded = candidate
            lower = size + 1
        else:
            upper = size - 1
    return encoded if encoded != '""' else ""


def format_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    used = 0
    # Spend the bounded extraction context on the latest corrections first;
    # restore chronological order before sending it to the model.
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        role = role.strip().lower() if isinstance(role, str) else ""
        content = message.get("content")
        content = content.strip() if isinstance(content, str) else ""
        if not content:
            continue
        speaker = "Пользователь" if role in ("user", "human") else "Ассистент (НЕ ИСТОЧНИК ФАКТОВ)"
        prefix = f"{speaker}: "
        separator = 1 if lines else 0
        remaining = TRANSCRIPT_LIMIT - used - separator - len(prefix)
        if remaining < 3:
            break
        encoded = _quoted_prefix(content, remaining)
        if encoded:
            lines.append(prefix + encoded)
            used += separator + len(prefix) + len(encoded)
    return "\n".join(reversed(lines))
