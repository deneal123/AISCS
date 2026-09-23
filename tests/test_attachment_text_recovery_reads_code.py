"""Восстановление текста вложения читает КОД и простой текст, а не только документы.

🔴 НАЙДЕНО ТЕМ ЖЕ СКВОЗНЫМ ПРОГОНОМ. Текст вложения извлекает сервер при загрузке и отдаёт
клиенту (`extracted_text`), а тот обязан вернуть его в `file_context` следующего сообщения.
Не вернул — сервер восстанавливает сам. Механизм заявлен и работал ТОЛЬКО для документов:
он гонит содержимое через `OpenDataLoaderParser`, а тот на `.py`, `.md`, `.json`, `.yaml`
возвращает ПУСТО — при любом ключе хранилища, проверено прямым замером.

Наружу это выглядело так: человек приложил `.py`, получил «пришлите код функции add» — при
том что файл лежит в хранилище, а текст из него уже был извлечён минутой раньше.

⚠️ Читаем ТЕМ ЖЕ приёмом, что и загрузка (декодирование UTF-8 + существующее правило
качества текста). Бинарь так не пролезет: после `errors="replace"` он рассыпается на
одиночные символы и не проходит порог. Честное пусто лучше мусора в промпте — за мусор
платят токенами КАЖДЫЙ ход треда.
"""

from __future__ import annotations

from service.services.chat.infrastructure.chat_worker.turn_context import (
    _RECOVERED_TEXT_LIMIT,
    decode_as_text,
)


def test_code_is_read_as_text():
    """🔴 ГЛАВНОЕ. Ровно тот файл из замера: парсер документов вернул на нём ноль."""
    out = decode_as_text(b"def add(a, b):\n    return a - b  # BUG\n")

    assert "def add" in out and "return a - b" in out


def test_plain_formats_are_read_too():
    """⚠️ Один класс поломки на все текстовые форматы, а не только на Python."""
    for content in (
        b"# Readme\n\nProject description goes here, with enough words to judge.\n",
        b'{"name": "config", "values": [1, 2, 3], "description": "sample settings"}\n',
        b"key: value\nother: setting\ncomment: enough words here to be judged as text\n",
    ):
        assert decode_as_text(content), f"текстовый формат прочитан как пусто: {content[:20]!r}"


def test_binary_does_not_pass_as_text():
    """🔴 ГРАНИЦА, БЕЗ КОТОРОЙ ПОЧИНКА ВРЕДИТ. Картинка или архив, продекодированные с
    `errors="replace"`, дали бы кашу — и она уехала бы в промпт, оплачиваясь каждый ход."""
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8

    assert decode_as_text(png) == "", "бинарь просочился в контекст как «текст»"


def test_empty_input_is_empty_output():
    """⚠️ Пусто и пробелы — это «нечего восстанавливать», а не повод положить в промпт строку."""
    assert decode_as_text(b"") == ""
    assert decode_as_text(b"   \n\t ") == ""
    assert decode_as_text(None) == ""


def test_the_text_is_bounded():
    """⚠️ Потолок тот же, что у загрузки: вложение едет в промпт КАЖДЫМ ходом треда, и
    «восстановить целиком» здесь означает платить за это каждый раз."""
    out = decode_as_text(("слово " * 20_000).encode())

    assert len(out) == _RECOVERED_TEXT_LIMIT


def test_recovery_falls_back_to_plain_text(monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а восстановление по-прежнему зовёт только парсер —
    и на коде снова вернёт ноль. Проверяем НАСТОЯЩИЙ путь, подменив только хранилище.
    """
    import asyncio

    from service.services.chat.infrastructure import chat_worker_tasks as cwt

    content = b"def add(a, b):\n    return a - b  # BUG\n"

    class _Row:
        file_name = "uploads/CHAT/deadbeef"

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return [_Row()]

    class _Session:
        async def execute(self, *_a, **_kw):
            return _Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

    class _Pg:
        def get_session_context(self):
            return _Session()

    class _Files:
        async def get_file_by_key(self, *, file_key):
            return content

    class _Parser:
        async def parse(self, *_a, **_kw):
            # Ровно то, что делает настоящий парсер на коде: пусто.
            return ""

    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.factory.build_file_service",
        lambda *_a, **_kw: _Files(),
    )
    monkeypatch.setattr(
        "service.services.chat.infrastructure.media.opendataloader_parser.OpenDataLoaderParser",
        _Parser,
    )
    monkeypatch.setattr(
        "service.infrastructure.agents_client.ports.resolve_user_uuid",
        lambda *_a, **_kw: "11111111-1111-1111-1111-111111111111",
    )

    out = asyncio.run(cwt._recover_attachment_text(_Pg(), object(), "u-1"))

    assert "def add" in out, (
        "восстановление снова опирается только на парсер документов — код останется невидимым"
    )
