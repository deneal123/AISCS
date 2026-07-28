"""Повторный импорт не возвращает файл к тому виду, в котором он лежит в хранилище.

🔴 НАЙДЕНО ЗАМЕРОМ. Импорт идёт НЕ ОДИН РАЗ: список файлов диалога уезжает в песочницу на
КАЖДОМ ходу. Запись была безусловной (`> файл`), поэтому второй ход затирал правки первого
— молча, без следа в ответе и без слова человеку или модели.

Сценарий, который от этого не работал вовсе: «поправь договор» → агент правит → «теперь
добавь пункт 5» → правок первого хода нет, агент правит пустое место, и человек получает
документ без своей первой просьбы. Замерено живьём: после второго импорта в файле снова
`price = 100` вместо `price = 250`.

Песочница — РАБОЧАЯ КОПИЯ, хранилище — источник, из которого она однажды заведена. Новая
версия файла приезжает НОВОЙ записью хранилища и ложится под отличающимся именем, так что
обновлению это правило не мешает.
"""

from __future__ import annotations

import inspect

import pytest

from service import app, importer


def test_an_existing_file_is_left_alone():
    """⚠️ ГЛАВНОЕ. Проверка существования стоит ДО записи, иначе она бесполезна."""
    command = importer.write_command("/workspace", "договор.txt", "из хранилища".encode())

    assert importer.EXISTS_MARKER in command, "существующий файл будет перезаписан"
    assert command.index(importer.EXISTS_MARKER) < command.index("base64 -d"), (
        "проверка стоит ПОСЛЕ записи — файл уже затёрт, когда о нём вспомнили"
    )
    assert "exit 0" in command.split("base64 -d")[0], (
        "после маркера команда продолжает выполняться и всё равно пишет"
    )


def test_a_new_file_is_still_written():
    """🔴 ГРАНИЦА. «Починка», после которой не импортируется НИЧЕГО, хуже исходной беды."""
    command = importer.write_command("/workspace", "новый.txt", "данные".encode())

    assert "base64 -d" in command
    assert "__OK__" in command


def test_the_path_is_still_checked_before_anything_else():
    """Проверка пути не должна была никуда деться из-за новой ветки."""
    with pytest.raises(importer.ImportRefused):
        importer.write_command("/workspace", "../../etc/passwd", b"x")


class _Result:
    def __init__(self, stdout: str):
        self.stdout, self.stderr, self.exit_code = stdout, "", 0


class _Item:
    def __init__(self):
        self.policy = type("P", (), {"root": "/workspace", "image": "img"})()
        self.imported: set[str] = set()
        self.workspace_id, self.user_id = "w-1", "u-1"


async def _drive_import(monkeypatch, stdout: str):
    """Прогнать НАСТОЯЩИЙ обработчик импорта, подменив только поход в контейнер и в сеть."""
    item = _Item()
    commits: list[str] = []
    monkeypatch.setattr(app, "_owned", lambda _wid, _p: (item, None))
    monkeypatch.setattr(app, "_auth", lambda _a: None)
    monkeypatch.setattr(app, "fetch", _returns(b"payload"))
    monkeypatch.setattr(app, "_run_file_op", _returns(_Result(stdout)))
    monkeypatch.setattr(app, "_snapshot", _records(commits))

    payload = app.ImportRequest(
        user_id="u-1", token="t", files=[{"name": "договор.txt", "url": "https://s/x"}]
    )
    out = await app.import_files("w-1", payload, authorization="Bearer k")
    return out, item, commits


def _returns(value):
    async def _call(*_a, **_kw):
        return value

    return _call


def _records(sink: list):
    async def _call(_item, message):
        sink.append(message)
        return {"committed": True, "reason": ""}

    return _call


@pytest.mark.asyncio
async def test_a_kept_file_is_reported_as_kept_not_as_a_failure(monkeypatch):
    """🔴 ТРЕТЬЕ СОСТОЯНИЕ, ПО ПОВЕДЕНИЮ. Пропуск — норма (импорт идёт каждый ход), и
    выдавать его за провал записи значит пугать вызывающего там, где всё в порядке."""
    out, item, _ = await _drive_import(monkeypatch, importer.EXISTS_MARKER)

    entry = out["files"][0]
    assert entry["kept"] is True, "пропуск неотличим от чего бы то ни было"
    assert entry["imported"] is False, "пропуск засчитан записью"
    assert "reason" not in entry, "пропуск выдан за отказ — вызывающий увидит несуществующий сбой"
    assert out["kept"] == 1
    assert "договор.txt" in item.imported, (
        "пропущенный файл перестал считаться импортированным — опись сочтёт его созданием "
        "агента и вернёт человеку его же вложение"
    )


@pytest.mark.asyncio
async def test_a_kept_file_adds_no_history_point(monkeypatch):
    """Точка «файлы пользователя» ставится по ФАКТУ записи. Иначе история копит пустые
    записи каждый ход — а по ней человек ищет, к чему возвращаться."""
    _, _, commits = await _drive_import(monkeypatch, importer.EXISTS_MARKER)

    assert commits == [], "пропуск поставил точку истории на ровном месте"


@pytest.mark.asyncio
async def test_a_written_file_does_add_one(monkeypatch):
    """🔴 БЕЗ ЭТОГО тест выше зелен и от «не коммитить никогда»."""
    out, _, commits = await _drive_import(monkeypatch, "__OK__ 7")

    assert out["files"][0]["imported"] is True
    assert commits == [app.IMPORT_MESSAGE], "запись не оставила точки, к которой возвращаться"


@pytest.mark.asyncio
async def test_a_real_failure_is_still_a_failure(monkeypatch):
    """Граница с третьей стороны: неудачная запись обязана остаться неудачной."""
    out, _, commits = await _drive_import(monkeypatch, "")

    entry = out["files"][0]
    assert entry["imported"] is False and "reason" in entry
    assert "kept" not in entry, "провал записи выдан за «файл уже лежит»"
    assert commits == []


def test_an_archive_is_not_unpacked_over_the_agents_edits():
    """⚠️ Разворот `.zip` — та же запись, только массовая: повторный затёр бы дерево."""
    src = inspect.getsource(app.import_files)

    unpack_at = src.index("unpack_command(")
    assert "if ok:" in src[:unpack_at], "разворот не привязан к СВЕЖЕЙ записи"
    assert "if ok or kept:" in src[: src.index("if ok:")], (
        "порядок веток изменился — разворот мог уехать под условие «или пропущен»"
    )
