"""Страж: web_search не должен снова звать `.human_repr()`.

Половина проверки, приехавшая вместе с модулем. Раньше она жила в backend
(``test_repo_url.py``) и покрывала оба инструмента разом; после разделения владения
``repo_fetcher`` остался у backend, а ``web_search`` уехал сюда — и страж обязан был
поехать за ним, иначе регрессия просто перестала бы ловиться.

``.human_repr()`` — метод yarl.URL, которого нет у urllib: вызов падал в рантайме на
разборе ссылки. В комментариях слово встречается намеренно, поэтому проверяем именно
ВЫЗОВ, а не упоминание.
"""

from __future__ import annotations

import importlib
from pathlib import Path


def test_web_search_does_not_call_human_repr() -> None:
    # importlib, а не `import ... as`: пакет tools реэкспортирует ФУНКЦИЮ web_search,
    # и она затеняет одноимённый модуль.
    module = importlib.import_module("service.domain.tools.web_search")
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert ".human_repr()" not in source, "web_search снова зовёт human_repr()"
