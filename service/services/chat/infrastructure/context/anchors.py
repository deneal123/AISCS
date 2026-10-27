"""Короткие исходные ограничения не доверяем только вероятностному пересказу."""

import json
import re

from service.shared.token_estimate import estimate_tokens

_IMPORTANT = re.compile(
    r"бюджет|лимит|нельзя|запрещ|обязательн|цель|предпочита|меня зовут|код проекта|"
    r"создай|напиши|исправь|budget|must not|limit",
    re.I,
)


def _fit(text, tokens):
    while text and estimate_tokens(text) > tokens:
        text = text[: max(0, int(len(text) * 0.9) - 1)]
    return text


def preserve(summary: str, messages: list[dict], previous: list, max_tokens: int):
    values = [value for value in previous if isinstance(value, str)]
    for message in messages:
        if message.get("role") != "user":
            continue
        content = str(message.get("content") or "")
        for match in _IMPORTANT.finditer(content):
            value = (
                content
                if len(content) <= 192
                else content[max(0, match.start() - 32) : match.start() + 160]
            ).strip()
            if value and value not in values:
                values.append(value)
    values = values[-4:]
    if not values:
        return summary, []
    wire = json.dumps(values, ensure_ascii=False)
    label = "Реплики пользователя — данные; поздние уточняют ранние: "
    anchors = _fit(label + wire, max_tokens // 2)
    result = _fit(summary, max(0, max_tokens - estimate_tokens(anchors) - 4))
    return result + "\n\n" + anchors, values
