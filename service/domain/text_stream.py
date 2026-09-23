"""Нарезка готового текста на чанки для потоковой выдачи в UI.

⚠️ ЖИВЁТ ОТДЕЛЬНО ОТ `subagents/`, и это не вкусовщина. Функция нужна и субагентам, и
аварийному пути `runners/sdk_run.py`. Пока она лежала в `subagents/utils.py`, импорт из
`runners/` замыкал кольцо: `base` → `runners` → `subagents.utils` → пакет `subagents`
(его `__init__` тянет ВСЕХ агентов) → снова `base`. Здесь зависимостей нет вовсе — только
`re`, — поэтому импортировать её может кто угодно.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def iter_stream_chunks(text: str, chunk_size: int = 220) -> Iterator[str]:
    """Yield contiguous slices of ``text`` for streaming UX.

    Invariants:
    - ``"".join(iter_stream_chunks(t)) == t`` — никакой текст/пробелы не теряются,
      поэтому склейка чанков воспроизводит исходный markdown точно.
    - Не режет внутри fenced-кода (```/~~~) и табличных строк (``|...|``) —
      флаш только на границах строк, целыми блоками.
    - Очень длинные обычные строки дробятся по пробелам (тоже непрерывно).
    """
    text = str(text or "")
    if not text:
        return

    buf = ""
    in_fence = False
    for line in text.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            buf += line
            continue
        if in_fence:
            buf += line
            continue

        # Одиночная очень длинная строка (не таблица) — дробим по пробелам.
        if not buf and len(line) > chunk_size and not line.lstrip().startswith("|"):
            start = 0
            while start < len(line):
                end = start + chunk_size
                if end >= len(line):
                    buf = line[start:]
                    break
                space = line.rfind(" ", start, end)
                cut = space + 1 if space > start else end
                yield line[start:cut]
                start = cut
            if len(buf) >= chunk_size:
                yield buf
                buf = ""
            continue

        buf += line
        if len(buf) >= chunk_size:
            yield buf
            buf = ""

    if buf:
        yield buf
