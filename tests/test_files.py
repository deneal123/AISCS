"""Файловые операции: путь не должен выходить за корень, чтение не должно врать.

Две проверяемые здесь вещи — те, ради которых операции и живут в сайдкаре, а не у
вызывающего: разбор пути рядом с политикой и честный признак обрезки при чтении.
"""

from __future__ import annotations

import base64
import shlex

import pytest
from files import (
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
    """Кавычки и переводы строк в содержимом иначе ломают команду целиком."""
    command = write_command(ROOT, "a.txt", "line1\n'; rm -rf /\nline3")
    assert "rm -rf" not in command
    assert "base64 -d" in command


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
    assert parse_read(base64.b64encode(b" ").decode()) == (" ", False)


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
    from files import parse_artifacts

    output = "12\t/workspace/данные.csv\n40\t/workspace/отчёт.md"
    artifacts = parse_artifacts(output, ROOT, {"данные.csv"})
    assert [a["path"] for a in artifacts] == ["отчёт.md"]


def test_artifact_paths_are_relative_to_the_root() -> None:
    """Абсолютный путь внутри контейнера наружу не нужен и только путает."""
    from files import parse_artifacts

    artifacts = parse_artifacts("7\t/workspace/sub/a.txt", ROOT, set())
    assert artifacts == [{"path": "sub/a.txt", "size": 7}]


def test_artifacts_walk_the_whole_depth_not_two_levels() -> None:
    """Артефакт мог родиться в подкаталоге: не заметить его хуже, чем показать лишнее."""
    from files import artifacts_command, list_command

    assert "-maxdepth" not in artifacts_command(ROOT)
    assert "-maxdepth" in list_command(ROOT, "")


def test_tool_directories_are_excluded() -> None:
    """Первый же `git init` или `pip install` иначе завалит ответ тысячами чужих файлов."""
    from files import artifacts_command

    command = artifacts_command(ROOT)
    for noisy in (".git", "node_modules", ".venv"):
        assert noisy in command and "-prune" in command


def test_broken_line_does_not_break_the_listing() -> None:
    from files import parse_artifacts

    artifacts = parse_artifacts("мусор\n5\t/workspace/ok.txt\n\t", ROOT, set())
    assert [a["path"] for a in artifacts] == ["ok.txt"]
