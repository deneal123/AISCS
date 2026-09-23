"""Ответ `/api/chats/parse-url` имеет ОДНУ форму для обеих веток.

У метода две ветки: ссылка на репозиторий → карта архитектуры, всё остальное →
разбор страницы сайдкаром. Возвращали они РАЗНОЕ: репозиторий — словарь
`{url, title, content, kind}`, обычная страница — голую строку, хотя метод
объявлен как `-> dict`.

Чем это оборачивалось у пользователя: фронт читает `r.value?.content`
(`useChatMessageSender.js:285`). У строки такого поля нет, поэтому страница
успешно скачивалась и разбиралась, а в чате появлялось «не удалось прочитать:
пустой ответ», и модель не получала текст вовсе. Работали только ссылки на
GitHub — то есть ровно та ветка, что возвращала словарь.

Найдено не тестом, а mypy: `Incompatible return value type (got "str",
expected "dict")`. Проверка типов до этого ни разу не выполнялась, потому что
pre-commit не был установлен.
"""

from __future__ import annotations

import pytest

from service.services.chat.application.chat_application_service import ChatApplicationService

# Поля, на которые опирается фронт. Именно их отсутствие делало ответ бесполезным.
_REQUIRED = {"url", "title", "content"}


class _FakeSidecar:
    """Заглушка `sidecar_tools`: отдаёт текст страницы, как настоящий модуль."""

    def __init__(self, content: str | None) -> None:
        self._content = content

    async def parse_url(self, _config, _url):  # noqa: ANN001 — сигнатура повторяет модуль
        return self._content


@pytest.fixture()
def service() -> ChatApplicationService:
    return ChatApplicationService.__new__(ChatApplicationService)


async def _call(service: ChatApplicationService, monkeypatch, url: str, content: str | None):
    import service.infrastructure.agents_client as agents_client

    monkeypatch.setattr(agents_client, "sidecar_tools", _FakeSidecar(content), raising=False)

    async def _not_a_repo(_self, _url):
        return None

    monkeypatch.setattr(ChatApplicationService, "_parse_repo_url", _not_a_repo, raising=True)
    return await service.parse_url_content(url=url)


@pytest.mark.asyncio
async def test_ordinary_url_returns_dict_with_content(service, monkeypatch):
    """Обычная ссылка → словарь с `content`, а не голая строка."""
    result = await _call(service, monkeypatch, "https://example.com/article", "текст страницы")

    assert isinstance(result, dict), "фронт читает r.value.content — строка ему бесполезна"
    assert _REQUIRED <= set(result), f"нет обязательных полей: {_REQUIRED - set(result)}"
    assert result["content"] == "текст страницы"


@pytest.mark.asyncio
async def test_shape_matches_repository_branch(service, monkeypatch):
    """Обе ветки отдают согласованный набор ключей.

    Смысл теста — не в конкретных именах, а в том, что ветки не разъезжаются:
    именно расхождение форм и было дефектом.
    """
    page = await _call(service, monkeypatch, "https://example.com/x", "текст")

    # Форма ветки репозитория зафиксирована в `_parse_repo_url`.
    repo_keys = {"url", "title", "content", "kind"}
    assert repo_keys <= set(page), f"ветки разошлись, не хватает: {repo_keys - set(page)}"
