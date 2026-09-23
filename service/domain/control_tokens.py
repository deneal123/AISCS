"""Служебные токены модели не должны доезжать до пользователя.

Модели иногда «проговаривают» собственную разметку шаблона диалога — `<|eom|>`,
`<|assistant|>`, `<|im_start|>`, `<|test_begin|>` и т.п. — обычным текстом. Это не наша
ошибка, но и не забота пользователя: в чате это выглядит как мусор, а попав в историю,
уезжает обратно в модель следующим запросом и добивает её окончательно.

Фильтр стейтфулен НАМЕРЕННО: токен приходит разорванным между дельтами стрима
(`<|` в одном чанке, `eom|>` в другом), и построчная зачистка его бы не увидела.
Незакрытый хвост придерживаем до следующего чанка, а на flush отдаём как есть — съесть
настоящий текст страшнее, чем пропустить один `<`.
"""

from __future__ import annotations

import re

# Внутрь токена не пускаем переносы и вложенные скобки: настоящая разметка коротка и
# однострочна. Потолок в 64 символа не даёт регэкспу схлопнуть пол-абзаца текста.
_CONTROL_TOKEN_RE = re.compile(r"<\|[^<>|\n]{0,64}\|>")

# Хвост чанка, который МОЖЕТ оказаться началом токена: `<`, `<|`, `<|assis`…
_PARTIAL_TAIL_RE = re.compile(r"<(?:\|[^<>|\n]{0,64})?$")


def strip_control_tokens(text: str) -> str:
    """Одноразовая зачистка целой строки (не-стримовые пути)."""
    return _CONTROL_TOKEN_RE.sub("", str(text or ""))


class ControlTokenFilter:
    """Потоковая зачистка. Один экземпляр на один стрим."""

    __slots__ = ("_pending",)

    def __init__(self) -> None:
        self._pending = ""

    def feed(self, chunk: str) -> str:
        buffer = self._pending + str(chunk or "")
        buffer = _CONTROL_TOKEN_RE.sub("", buffer)

        tail = _PARTIAL_TAIL_RE.search(buffer)
        if tail:
            self._pending = buffer[tail.start() :]
            return buffer[: tail.start()]

        self._pending = ""
        return buffer

    def flush(self) -> str:
        """Остаток в конце стрима. Незакрытый хвост — не токен, а просто текст."""
        tail, self._pending = self._pending, ""
        return _CONTROL_TOKEN_RE.sub("", tail)
