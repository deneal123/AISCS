"""Имена инструментов чужого MCP-сервера: приведение к безопасному виду.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Имя приходит ИЗ ЧУЖОГО СЕРВИСА и попадает сразу в три места:
в JSON-схему запроса к провайдеру, в ключ словаря наших инструментов и в трейс. Каждое со
своими ограничениями — у OpenAI-совместимых провайдеров имя функции ограничено 64 символами
и алфавитом `[A-Za-z0-9_-]`, а имя-дубль молча затирает наш родной инструмент.

🔴 Префикс `mcp_<сервер>__` обязателен и служит ДВУМ целям сразу: по нему видно источник
(«кто это вообще предложил») и он делает столкновение с родным именем невозможным. Без него
сервер, объявивший инструмент `search_web`, подменил бы наш — и подмену нечем было бы
заметить.
"""

from __future__ import annotations

import re

_PREFIX = "mcp_"
_SEP = "__"
# Потолки под самый строгий известный лимит провайдера (64 символа на имя функции).
MAX_TOTAL = 64
MAX_SERVER_SLUG = 24
MAX_TOOL_SLUG = 32

_ALLOWED = re.compile(r"[^A-Za-z0-9_]+")
_VALID_NAME = re.compile(rf"^{_PREFIX}[A-Za-z0-9_]+{_SEP}[A-Za-z0-9_]+$")


def slug(raw: str, limit: int) -> str:
    """Привести кусок имени к `[A-Za-z0-9_]` и обрезать до потолка."""
    cleaned = _ALLOWED.sub("_", str(raw or "").strip()).strip("_")
    return cleaned[:limit].strip("_")


def make_tool_name(server_id: str, tool_name: str) -> str | None:
    """`mcp_<сервер>__<инструмент>` или `None`, если собрать безопасное имя нельзя.

    ⚠️ `None`, а не «как-нибудь»: имя, которое провайдер отвергнет, роняет ВЕСЬ запрос, а
    не только этот инструмент. Пропустить один инструмент дешевле, и пропуск не молчит —
    он уезжает отказом с причиной.
    """
    server = slug(server_id, MAX_SERVER_SLUG)
    tool = slug(tool_name, MAX_TOOL_SLUG)
    if not server or not tool:
        return None
    # ⚠️ Длину НЕ проверяем повторно: потолки слагов её уже гарантируют, и проверка была бы
    # недостижимой — то есть непроверяемой. Гарантию держит арифметический инвариант в тесте:
    # он краснеет, если кто-то поднимет потолок и сумма перестанет влезать в лимит провайдера.
    name = f"{_PREFIX}{server}{_SEP}{tool}"
    return name if _VALID_NAME.match(name) else None


def parse_tool_name(name: str) -> tuple[str, str] | None:
    """Разобрать обратно: имя → (сервер, инструмент). `None` — имя не наше."""
    text = str(name or "")
    if not _VALID_NAME.match(text):
        return None
    server, _, tool = text[len(_PREFIX) :].partition(_SEP)
    return (server, tool) if server and tool else None
