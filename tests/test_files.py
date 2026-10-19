"""Файловые операции: путь не должен выходить за корень, чтение не должно врать.

Две проверяемые здесь вещи — те, ради которых операции и живут в сайдкаре, а не у
вызывающего: разбор пути рядом с политикой и честный признак обрезки при чтении.
"""

from __future__ import annotations

import base64
import shlex

import pytest
from domain import files
from domain.files import (
    MAX_READ_BYTES,
    UnsafePath,
    grep_command,
    list_command,
    parse_read,
    read_command,
    safe_path,
    write_command,
)

ROOT = "/workspace"


# --- путь ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "sub/../../etc/passwd",
        "/etc/passwd",
        "/workspace/../etc/shadow",
        "/workspace-evil/secret",  # 🔴 префикс совпадает, каталог ДРУГОЙ
        "./../../root/.ssh/id_rsa",
    ],
)
def test_paths_leaving_the_root_are_refused(path: str) -> None:
    with pytest.raises(UnsafePath):
        safe_path(ROOT, path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a.txt", "/workspace/a.txt"),
        ("sub/b.txt", "/workspace/sub/b.txt"),
        ("./c.txt", "/workspace/c.txt"),
        ("/workspace/d.txt", "/workspace/d.txt"),
        ("sub/../e.txt", "/workspace/e.txt"),  # нормализация внутри корня законна
        ("", "/workspace"),
    ],
)
def test_paths_inside_the_root_resolve(path: str, expected: str) -> None:
    assert safe_path(ROOT, path) == expected


def test_root_itself_is_allowed() -> None:
    assert safe_path(ROOT, ROOT) == ROOT


# --- экранирование ------------------------------------------------------------------


@pytest.mark.parametrize(
    "evil",
    [
        "a.txt; rm -rf /",
        "a.txt' ; cat /etc/passwd ; echo '",
        "$(whoami).txt",
        "`id`.txt",
        "a.txt\nrm -rf /",
    ],
)
def test_command_injection_through_a_filename_is_quoted_away(evil: str) -> None:
    """🔴 Имя файла придумывает МОДЕЛЬ. Без экранирования это выполнение чужой команды.

    ⚠️ Проверяем НЕ отсутствие подстроки: `shlex.quote` оставляет текст на месте и лишь
    обезвреживает его кавычками, так что проверка «нет подстроки» краснела бы на исправном
    коде. Правильный вопрос — сколько получилось АРГУМЕНТОВ: опасное имя обязано остаться
    ОДНИМ токеном, а не превратиться в отдельную команду.
    """
    tokens = shlex.split(read_command(ROOT, evil))
    assert safe_path(ROOT, evil) in tokens, tokens
    assert not {"rm", "whoami", "id", "cat"} & set(tokens), tokens


def test_grep_pattern_is_quoted_too() -> None:
    pattern = "'; rm -rf / ; echo '"
    tokens = shlex.split(grep_command(ROOT, pattern, ""))
    assert pattern in tokens
    assert "rm" not in tokens


def test_write_content_travels_base64_not_inline() -> None:
    """Кавычки и переводы строк в содержимом иначе ломают команду целиком.

    ⚠️ Содержимое едет ОТДЕЛЬНО от команды (stdin): в аргументах ему не место — см.
    `test_file_content_never_travels_in_argv`.
    """
    command, payload = write_command(ROOT, "a.txt", "line1\n'; rm -rf /\nline3")
    assert "rm -rf" not in command
    assert "base64 -d" in command
    assert base64.b64decode(payload).decode() == "line1\n'; rm -rf /\nline3"


# --- чтение не врёт -------------------------------------------------------------------


def test_read_reports_truncation() -> None:
    """🔴 Молча обрезанное чтение — НЕВЕРНОЕ чтение: модель не узнает, что видит половину."""
    payload = base64.b64encode(b"x" * (MAX_READ_BYTES + 100)).decode()
    content, truncated = parse_read(payload)
    assert truncated and len(content) == MAX_READ_BYTES


def test_read_of_a_full_file_is_not_marked_truncated() -> None:
    payload = base64.b64encode("привет".encode()).decode()
    content, truncated = parse_read(payload)
    assert content == "привет" and not truncated


def test_missing_file_is_distinguishable_from_an_empty_one() -> None:
    """Пустой файл и отсутствующий — разные ответы; иначе «нет файла» выглядит как «пусто»."""
    with pytest.raises(FileNotFoundError):
        parse_read("__MISSING__")
    with pytest.raises(FileNotFoundError):
        parse_read("")
    assert parse_read("__EMPTY__\n") == ("", False)
    assert parse_read(base64.b64encode(b" ").decode()) == (" ", False)


def test_read_command_emits_an_explicit_empty_file_receipt() -> None:
    command = read_command(ROOT, "empty.bib")
    assert command.index("__MISSING__") < command.index("__EMPTY__") < command.index("head -c")
    assert "[ ! -s " in command


def test_binary_content_does_not_crash_the_read() -> None:
    payload = base64.b64encode(b"\xff\xfe\x00binary").decode()
    content, _ = parse_read(payload)
    assert "binary" in content


# --- потолки ---------------------------------------------------------------------------


def test_oversized_write_is_refused_before_reaching_the_container() -> None:
    with pytest.raises(ValueError):
        write_command(ROOT, "big.bin", "x" * (2 * 1024 * 1024))


def test_list_is_bounded() -> None:
    assert "head -n 500" in list_command(ROOT, "")


# --- артефакты ------------------------------------------------------------------------


def test_imported_files_are_not_reported_as_artifacts() -> None:
    """🔴 Вернуть человеку его же файл значит сообщить, что агент его создал."""
    from domain.files import parse_artifacts

    output = "12\t/workspace/данные.csv\n40\t/workspace/отчёт.md"
    artifacts = parse_artifacts(output, ROOT, {"данные.csv"})
    assert [a["path"] for a in artifacts] == ["отчёт.md"]


def test_artifact_paths_are_relative_to_the_root() -> None:
    """Абсолютный путь внутри контейнера наружу не нужен и только путает."""
    from domain.files import parse_artifacts

    artifacts = parse_artifacts("7\t/workspace/sub/a.txt", ROOT, set())
    assert artifacts == [{"path": "sub/a.txt", "size": 7}]


def test_artifacts_walk_the_whole_depth_not_two_levels() -> None:
    """Артефакт мог родиться в подкаталоге: не заметить его хуже, чем показать лишнее."""
    from domain.files import artifacts_command, list_command

    assert "-maxdepth" not in artifacts_command(ROOT)
    assert "-maxdepth" in list_command(ROOT, "")


def test_tool_directories_are_excluded() -> None:
    """Первый же `git init` или `pip install` иначе завалит ответ тысячами чужих файлов."""
    from domain.files import artifacts_command

    command = artifacts_command(ROOT)
    for noisy in (".git", "node_modules", ".venv"):
        assert noisy in command and "-prune" in command


def test_broken_line_does_not_break_the_listing() -> None:
    from domain.files import parse_artifacts

    artifacts = parse_artifacts("мусор\n5\t/workspace/ok.txt\n\t", ROOT, set())
    assert [a["path"] for a in artifacts] == ["ok.txt"]


# --- выгрузка артефакта: побайтово ------------------------------------------------------


def test_download_keeps_bytes_intact_where_read_would_corrupt_them() -> None:
    """🔴 Тот самый мотив ручки: `.xlsx` и картинка после текстового разбора НЕ ОТКРОЮТСЯ.

    `parse_read` декодирует utf-8 с заменой битых байт — это порча, а не неточность.
    Выгрузка обязана возвращать содержимое как есть.
    """
    from domain.files import parse_download, parse_read

    payload = base64.b64encode(b"PK\x03\x04\xff\xfe\x00zip").decode()
    raw, truncated = parse_download(payload)
    assert base64.b64decode(raw) == b"PK\x03\x04\xff\xfe\x00zip"
    assert not truncated
    # А текстовое чтение те же байты искажает — потому ручки и разные.
    text, _ = parse_read(payload)
    assert text.encode("utf-8", "replace") != b"PK\x03\x04\xff\xfe\x00zip"


def test_download_reports_truncation_so_a_partial_file_is_never_passed_off_as_whole() -> None:
    from domain.files import MAX_DOWNLOAD_BYTES, parse_download

    _, truncated = parse_download(base64.b64encode(b"x" * (MAX_DOWNLOAD_BYTES + 10)).decode())
    assert truncated


def test_download_has_a_bigger_ceiling_than_read() -> None:
    """Читает МОДЕЛЬ и платит за токены; выгружает backend в хранилище — задачи разные."""
    from domain.files import MAX_DOWNLOAD_BYTES, MAX_READ_BYTES

    assert MAX_DOWNLOAD_BYTES > MAX_READ_BYTES


def test_missing_artifact_is_distinguishable() -> None:
    from domain.files import parse_download

    with pytest.raises(FileNotFoundError):
        parse_download("__MISSING__")
    with pytest.raises(FileNotFoundError):
        parse_download("")
    assert parse_download("__EMPTY__\n") == ("", False)


def test_download_path_is_checked_like_any_other() -> None:
    from domain.files import download_command

    with pytest.raises(UnsafePath):
        download_command(ROOT, "../../etc/shadow")


def test_null_byte_is_refused_before_it_reaches_the_process() -> None:
    """🔴 NUL завершает строку в syscall `exec` — попытка передать его роняет СОЗДАНИЕ
    процесса целиком, и наружу уходило нечитаемое «Internal Server Error». Модель такую
    строку сочиняет запросто; отказ обязан быть внятным."""
    from domain.files import reject_control_bytes

    with pytest.raises(UnsafePath):
        reject_control_bytes("echo \x00 hi", "команда")
    with pytest.raises(UnsafePath):
        safe_path(ROOT, "a\x00.txt")
    assert reject_control_bytes("echo ok", "команда") == "echo ok"


def test_bare_slash_means_my_own_root() -> None:
    """🔴 Живой прогон: модель попросила «/», получила отказ и сообщила пользователю, что
    не может читать файлы вообще. Формально верно, по делу бесполезно."""
    assert safe_path(ROOT, "/") == ROOT


def test_other_absolute_paths_are_still_refused() -> None:
    """Послабление касается ТОЛЬКО голого «/»: побег остаётся побегом."""
    for path in ("/etc/passwd", "/root/.ssh/id_rsa", "/var/run/docker.sock"):
        with pytest.raises(UnsafePath):
            safe_path(ROOT, path)


# --- дерево для панели и история версий ------------------------------------------------


def test_tree_prunes_service_directories():
    """🔴 `.git` и `node_modules` в дереве рабочего места не показываем.

    История песочницы не является её содержимым: показанная файлами, она поехала бы
    пользователю и раздула бы выгрузку. `node_modules` — просто стена вместо дерева, и
    отсекать его надо ДО обхода, иначе он съедает потолок записей и время.
    """
    command = files.tree_command("/workspace", "")

    assert "-prune" in command
    for name in (".git", "node_modules", "__pycache__"):
        assert f"-name {name}" in command or f"-name '{name}'" in command


def test_tree_stays_inside_the_sandbox():
    with pytest.raises(files.UnsafePath):
        files.tree_command("/workspace", "../etc")


def test_tree_is_deeper_than_the_model_listing():
    """Панель и модель — разные потребители: у модели два уровня, человеку нужно дерево."""
    assert files.MAX_TREE_DEPTH > 2
    assert "-maxdepth 2 " in files.list_command("/workspace", "")


def test_model_listing_hides_the_service_directories_too():
    """🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. `.git` завёлся ради истории — и полез в листинг МОДЕЛИ.

    Прогон показал ей `.git/config`, `.git/HEAD`, `.git/refs`: оплаченные токены за
    служебные потроха и приглашение принять их за результат работы. Отсечка была только
    в дереве для панели — а модель смотрит через `files/list`.
    """
    command = files.list_command("/workspace", "")

    assert "-prune" in command
    for name in (".git", "node_modules", "__pycache__"):
        assert f"-name {name}" in command or f"-name '{name}'" in command


def test_listing_and_tree_prune_the_same_set():
    """Два потребителя, одно правило: разъедься списки — `.git` вернулся бы к одному."""
    assert files.TREE_PRUNED_DIRS == files.PRUNED_DIRS


def test_git_init_sets_the_committer():
    """⚠️ Без личности `git commit` в контейнере без конфига ОТКАЗЫВАЕТСЯ, и история
    молча не ведётся."""
    command = files.git_init_command("/workspace", "GPTHub Agent <agent@gpthub.local>")

    assert "git config user.name" in command
    assert "git config user.email" in command
    assert "agent@gpthub.local" in command


def test_git_commands_survive_an_image_without_git():
    """Образ рантайма могли подменить: отвечаем маркером, а не падаем на первой команде."""
    for command in (
        files.git_init_command("/workspace", "A <a@b.c>"),
        files.git_commit_command("/workspace", "правка"),
        files.git_log_command("/workspace"),
        files.git_diff_command("/workspace"),
        files.git_revert_command("/workspace", "abc123"),
    ):
        assert "__NO_GIT__" in command


def test_commit_message_is_quoted():
    """Сообщение приходит из запроса пользователя — кавычки в нём не должны исполняться.

    ⚠️ Проверяем, что текст доехал ОДНИМ shell-аргументом, а не «нет опасной подстроки»:
    подстрока-то остаётся, вопрос лишь в том, аргумент это или команда.
    """
    payload = "'; rm -rf / ; echo '"
    command = files.git_commit_command("/workspace", payload)

    assert shlex.quote(payload) in command
    # Разбор шеллом отдаёт его ОДНИМ токеном — значит это аргумент, а не команда.
    assert payload in shlex.split(command)


def test_revert_needs_a_revision():
    with pytest.raises(files.UnsafePath):
        files.git_revert_command("/workspace", "  ")


def test_revert_scopes_the_path_to_the_sandbox():
    with pytest.raises(files.UnsafePath):
        files.git_revert_command("/workspace", "abc123", "../../etc/passwd")


def test_revert_uses_checkout_not_reset():
    """🔴 Откат ОДНОГО файла не должен сносить остальную работу и стирать историю."""
    command = files.git_revert_command("/workspace", "abc123", "main.py")

    assert "git checkout" in command
    assert "reset --hard" not in command


def test_log_parser_reads_entries_and_tolerates_absence():
    parsed = files.parse_git_log("a1b2c3\t2026-07-28T10:00:00+00:00\tпервый снимок")

    assert parsed == [
        {"ref": "a1b2c3", "at": "2026-07-28T10:00:00+00:00", "message": "первый снимок"}
    ]
    assert files.parse_git_log("__NO_GIT__") == []
    assert files.parse_git_log("") == []
