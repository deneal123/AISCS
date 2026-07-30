"""Содержимое файла едет через stdin, а не в аргументах команды.

🔴 ПОЛОМКА, КОТОРУЮ НАШЁЛ ЖИВОЙ ПРОГОН, А НЕ ТЕСТЫ. Человек загрузил `src.zip`, получил
песочницу — и пустой каталог, «никакого интерактива». В логе сайдкара:

    OSError: [Errno 7] Argument list too long: 'docker'

Содержимое клалось base64 прямо в argv, а у Linux потолок ОДНОГО аргумента — 128 КБ
(`MAX_ARG_STRLEN`), то есть ~96 КБ исходных байт. Заявленный же потолок стоял 1 МБ и до
проверки дело не доходило: `execve` падал раньше. Вместо внятного отказа приходил сырой
`OSError`, и снаружи это выглядело как «песочница есть, а файлов в ней нет».

⚠️ Окно поломки было ДВУСТОРОННИМ: 96 КБ…1.5 МБ ронялись, а всё выше 1.5 МБ отказывалось
вопреки скачиванию, разрешённому до 32 МБ. Один импорт с двумя разными границами.

⚠️ Прежние тесты записи это увидеть не могли: они звали `write_command` на строке в
несколько байт и разбирали её `shlex.split`. Команда была верной — негодным был ТРАНСПОРТ.
Поэтому здесь проверяется РАЗМЕР аргументов, а не их состав.
"""

from __future__ import annotations

import pytest

from files import MAX_WRITE_BYTES
from files import write_command as fs_write_command
from importer import MAX_FILE_BYTES, ImportRefused
from importer import write_command as import_command

ROOT = "/workspace"

# Потолок ОДНОГО элемента argv в Linux: `MAX_ARG_STRLEN` = 32 страницы = 128 КБ. Не
# настройка и не квота — константа ядра, менять её нельзя, обойти можно только каналом.
MAX_ARG_STRLEN = 128 * 1024


def _longest_argument(command: str) -> int:
    """Верхняя оценка самого длинного элемента argv: длина ВСЕЙ команды.

    ⚠️ Мерим целое, а не разбираем на токены, и это не упрощение, а необходимость: `execve`
    получает команду одним аргументом `sh -c`, поэтому её полная длина и есть та величина,
    которую сравнивают с потолком. Заодно оценка строгая — ни один элемент не может быть
    длиннее строки, из которой он вырезан.

    ⚠️ Первая редакция теста звала здесь `shlex.split`, и на 4 МБ base64 он ВИСЕЛ дольше
    двух минут: страж, не успевающий ответить, не отличим от отсутствующего.
    """
    return len(command)


# --- граница ядра ----------------------------------------------------------------------- #


def test_a_real_archive_fits_in_argv_because_it_is_not_there():
    """🔴 ГЛАВНОЕ. 4 МБ архива — ровно тот случай, что упал живьём."""
    data = b"PK\x03\x04" + b"\x00" * (4 * 1024 * 1024)

    command, payload = import_command(ROOT, "src.zip", data)

    assert _longest_argument(command) < MAX_ARG_STRLEN, (
        "содержимое снова в аргументах — `execve` упадёт с «Argument list too long» "
        "ЕЩЁ ДО контейнера, и снаружи это выглядит как пустая песочница"
    )
    assert len(payload) > len(data), "содержимое не поехало каналом — импортировать нечего"


def test_the_write_endpoint_has_the_same_property():
    """⚠️ Обычная запись агента — та же граница: файл на 200 КБ падал так же."""
    command, payload = fs_write_command(ROOT, "notes.md", "я" * 200_000)

    assert _longest_argument(command) < MAX_ARG_STRLEN
    assert payload, "содержимое не поехало каналом"


@pytest.mark.parametrize("size", [96 * 1024, 512 * 1024, 1024 * 1024, 8 * 1024 * 1024])
def test_no_size_below_the_import_ceiling_overflows_argv(size):
    """🔴 ОКНО ПОЛОМКИ ЦЕЛИКОМ. 96 КБ — где начиналось падение, 1 МБ — где прежний потолок
    начинал отказывать, 8 МБ — обычный архив с кодом."""
    command, _ = import_command(ROOT, "big.zip", b"x" * size)

    assert _longest_argument(command) < MAX_ARG_STRLEN


# --- команда читает stdin --------------------------------------------------------------- #


def test_the_command_actually_reads_the_channel_it_is_given():
    """⚠️ Короткого argv недостаточно: команда, не читающая stdin, создала бы ПУСТОЙ файл —
    отказ ещё тише прежнего."""
    command, _ = import_command(ROOT, "a.txt", b"data")

    assert "base64 -d" in command, "содержимое не декодируется"
    assert "printf" not in command, "содержимое всё ещё подставляется в команду"


def test_content_is_base64_not_raw_bytes():
    """⚠️ Сырые байты в stdin означали бы, что канал обязан быть бинарно прозрачным, а
    нулевой байт — отличим от конца. base64 есть в любом образе и этих вопросов не задаёт."""
    import base64

    raw = b"\xff\xd8\xff\x00\n' rm -rf /"
    _, payload = import_command(ROOT, "img.bin", raw)

    assert base64.b64decode(payload) == raw, "содержимое искажено — файл приедет битым"


# --- потолки ---------------------------------------------------------------------------- #


def test_the_import_ceiling_is_the_download_ceiling():
    """🔴 ВТОРАЯ ПОЛОВИНА ДЕФЕКТА. Запись отказывала на 1 МБ, скачивание разрешало 32 МБ:
    честно скачанный архив на 5 МБ получал отказ вопреки разрешению."""
    command, _ = import_command(ROOT, "ok.zip", b"x" * (5 * 1024 * 1024))
    assert command, "файл в пределах разрешённого скачивания отказан на записи"

    with pytest.raises(ImportRefused) as exc:
        import_command(ROOT, "huge.zip", b"x" * (MAX_FILE_BYTES + 1))
    assert str(MAX_FILE_BYTES) in str(exc.value), "отказ не называет границу"


def test_the_write_ceiling_is_checked_on_raw_bytes():
    """⚠️ Потолок тела запроса на запись остаётся своим — он про РАЗМЕР ТЕЛА, не про argv.
    Проверять его надо по сырым байтам: по base64 он был вдвое щедрее заявленного."""
    with pytest.raises(ValueError):
        fs_write_command(ROOT, "big.bin", "x" * (MAX_WRITE_BYTES + 1))


def test_a_refusal_is_clean_not_an_oserror():
    """🔴 ЧЕМ ЭТО КОНЧАЛОСЬ. Сырой `OSError` из драйвера не имел ни имени файла, ни причины:
    вызывающий получал 500, а человек — пустую песочницу без объяснений."""
    with pytest.raises(ImportRefused):
        import_command(ROOT, "huge.zip", b"x" * (MAX_FILE_BYTES + 1))


# --- точка вызова ----------------------------------------------------------------------- #
#
# 🔴 ВЕРНАЯ КОМАНДА НИЧЕГО НЕ ЗНАЧИТ, ЕСЛИ СОДЕРЖИМОЕ ДО ДРАЙВЕРА НЕ ДОЕХАЛО. Ровно этот
# класс уже трижды переживал мои мутации: правило проверено, а поломка живёт В МЕСТЕ
# ВЫЗОВА. Здесь команда читала бы stdin, драйвер бы его не подал — и в песочнице появился
# бы ПУСТОЙ файл. Отказ тише прежнего: он выглядит как успешный импорт.


class _Result:
    def __init__(self, stdout: str):
        self.stdout, self.stderr, self.exit_code = stdout, "", 0


class _Item:
    def __init__(self):
        self.policy = type("P", (), {"root": ROOT, "image": "img"})()
        self.imported: set[str] = set()
        self.workspace_id, self.user_id = "w-1", "u-1"


@pytest.mark.asyncio
async def test_the_import_handler_hands_the_content_to_the_driver(monkeypatch):
    """🔴 Прогоняем НАСТОЯЩИЙ обработчик, подменяя только поход в сеть и в контейнер."""
    import app

    # ⚠️ СПИСОК, а не словарь: за записью идёт разворот архива, у которого содержимого нет
    # по построению. Первая редакция теста держала последний вызов и краснела на разворот —
    # то есть проверяла бы не то, о чём заявлена.
    calls: list[tuple[str, bytes | None]] = []

    async def _file_op(_item, command, *, stdin_payload=None):
        calls.append((command, stdin_payload))
        return _Result("__OK__ 4")

    async def _returns(value):
        return value

    monkeypatch.setattr(app, "_owned", lambda _wid, _p: (_Item(), None))
    monkeypatch.setattr(app, "_auth", lambda _a: None)
    monkeypatch.setattr(app, "fetch", lambda *_a, **_kw: _returns(b"PK\x03\x04data"))
    monkeypatch.setattr(app, "_run_file_op", _file_op)
    monkeypatch.setattr(app, "_snapshot", lambda *_a, **_kw: _returns({"committed": True}))
    monkeypatch.setattr(app, "unpack_command", lambda *_a, **_kw: "true")

    await app.import_files(
        "w-1",
        app.ImportRequest(
            user_id="u-1", token="t", files=[{"name": "src.zip", "url": "https://s/x"}]
        ),
        authorization="Bearer k",
    )

    import base64

    carried = [payload for _command, payload in calls if payload]
    assert carried, "содержимое до драйвера не доехало — в песочнице появился бы ПУСТОЙ файл"
    assert base64.b64decode(carried[0]) == b"PK\x03\x04data"


@pytest.mark.asyncio
async def test_the_write_handler_hands_the_content_to_the_driver(monkeypatch):
    """⚠️ Второй вход в ту же запись. Один почин двух вызовов — обычное дело: у меня
    расходились и не такие пары."""
    import app

    seen = {}

    async def _file_op(_item, command, *, stdin_payload=None):
        seen.update({"command": command, "payload": stdin_payload})
        return _Result("__OK__ 6")

    async def _returns(value):
        return value

    monkeypatch.setattr(app, "_owned", lambda _wid, _p: (_Item(), None))
    monkeypatch.setattr(app, "_auth", lambda _a: None)
    monkeypatch.setattr(app, "_run_file_op", _file_op)
    monkeypatch.setattr(app, "_snapshot", lambda *_a, **_kw: _returns({"committed": True}))

    await app.write_file(
        "w-1",
        app.FileRequest(user_id="u-1", token="t", path="a.txt", content="данные"),
        authorization="Bearer k",
    )

    import base64

    assert base64.b64decode(seen["payload"]).decode() == "данные", (
        "запись отдала драйверу не то содержимое или не отдала вовсе"
    )


# --- маршрутизация в реестре ------------------------------------------------------------ #
#
# 🔴 СЛОЙ, КОТОРЫЙ БЫЛ СЛЕП. Оба теста выше подменяют `_run_file_op` ЦЕЛИКОМ, поэтому
# `exec_raw` в них не участвует: мутация «реестр игнорирует канал и уходит в обычный exec»
# оставила все 147 тестов зелёными. Ровно тот случай, когда два слоя прячут друг друга —
# верхний подменён, нижнего не звал никто. Проверяем реестр отдельно.


class _RecordingDriver:
    """Двойник драйвера, различающий ДВА пути исполнения."""

    name = "recording"

    def __init__(self):
        self.plain: list[str] = []
        self.with_input: list[tuple[str, bytes | None]] = []

    async def exec(self, _ref, command, *, timeout_sec, max_output_chars):
        self.plain.append(command)
        return _Result("__OK__")

    async def exec_with_input(self, _ref, command, *, payload, timeout_sec, max_output_chars):
        self.with_input.append((command, payload))
        return _Result("__OK__")


def _registry_item():
    from core import Workspace
    from policy import policy_from_request

    return Workspace(
        workspace_id="w-1",
        user_id="u-1",
        ref=type("R", (), {"container_id": "c-1"})(),
        policy=policy_from_request(None),
        expires_at=9_999_999_999.0,
    )


@pytest.mark.asyncio
async def test_the_registry_uses_the_stdin_path_when_content_is_given():
    """🔴 Содержимое есть — идём путём с каналом. Иначе байты просто пропадают: команда
    ждёт stdin, ей его не подают, и в песочнице появляется ПУСТОЙ файл."""
    from core import WorkspaceRegistry

    driver = _RecordingDriver()
    registry = WorkspaceRegistry(driver)

    await registry.exec_raw(
        _registry_item(), "base64 -d > a.txt", max_output_chars=1000, stdin_payload=b"ZGF0YQ=="
    )

    assert driver.with_input == [("base64 -d > a.txt", b"ZGF0YQ==")], (
        "реестр ушёл обычным путём — содержимое до контейнера не доехало"
    )
    assert not driver.plain


@pytest.mark.asyncio
async def test_the_registry_keeps_the_plain_path_for_everything_else():
    """🔴 ГРАНИЦА. Обычные команды обязаны идти прежним путём: у него `setsid`-обёртка,
    которой добивают группу процессов по таймауту, а у канального пути её нет намеренно."""
    from core import WorkspaceRegistry

    driver = _RecordingDriver()
    registry = WorkspaceRegistry(driver)

    await registry.exec_raw(_registry_item(), "ls -la", max_output_chars=1000)

    assert driver.plain == ["ls -la"]
    assert not driver.with_input, "чужая команда поехала путём без добивания группы"
