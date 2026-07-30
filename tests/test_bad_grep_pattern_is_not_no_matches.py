"""Негодный шаблон поиска отличается от «ничего не найдено».

🔴 НАЙДЕНО ЗАМЕРОМ НА ЖИВОЙ ПЕСОЧНИЦЕ. Поиск по `[unclosed` возвращал ровно тот же ответ,
что честный поиск без совпадений:

    {"matches": [], "truncated": false}

То есть НЕСОСТОЯВШИЙСЯ поиск выдавался за состоявшийся. Наружу это ложноотрицательный
результат: модель уверенно отвечает «в коде такого нет», хотя grep не искал вовсе. Хуже
любого отказа — отказ хотя бы виден и человеку, и модели.

Причина двойная, и каждая половина сама по себе достаточна:
* `2>/dev/null` глушил сообщение grep об ошибке шаблона;
* пайп в `head` подменял код возврата grep своим.

⚠️ `dash` (это `/bin/sh` в образе песочницы) не знает `pipefail`, поэтому код возврата
сквозь пайп не поймать. Шаблон проверяется ОТДЕЛЬНЫМ вызовом на пустом вводе: `grep`
отвечает 1 на «не найдено» и >1 на негодный шаблон, а дерево для этого обходить не нужно.
"""

from __future__ import annotations

import shlex

from files import BAD_PATTERN_MARKER, grep_command

ROOT = "/workspace"


def test_the_pattern_is_validated_before_the_search():
    """🔴 ГЛАВНОЕ. В команде есть проверка шаблона, и она стоит ДО обхода дерева."""
    command = grep_command(ROOT, "def request", "")

    assert BAD_PATTERN_MARKER in command, "негодный шаблон ничем не отличить от пустого поиска"
    assert command.index(BAD_PATTERN_MARKER) < command.rindex("grep -rnI"), (
        "проверка стоит ПОСЛЕ поиска — дерево уже обошли, а ошибку так и не отличили"
    )


def test_the_check_does_not_walk_the_tree():
    """⚠️ Проверка обязана быть ДЕШЁВОЙ: она идёт на каждый поиск. Пустой ввод вместо
    рекурсии по репозиторию — grep всё равно разбирает шаблон до чтения данных."""
    command = grep_command(ROOT, "x", "")
    head = command[: command.index(BAD_PATTERN_MARKER)]

    assert "printf '' |" in head, "шаблон проверяется не на пустом вводе"
    assert "-r" not in head.replace("-rnI", ""), "проверка шаблона рекурсивная — это лишняя работа"


def test_a_bad_pattern_stops_the_command():
    """⚠️ После маркера команда обязана ЗАВЕРШИТЬСЯ: иначе поиск всё равно выполнится и
    вернёт пустой список рядом с маркером — то есть снова два смысла в одном ответе."""
    command = grep_command(ROOT, "[unclosed", "")
    before_search = command[: command.rindex("grep -rnI")]

    assert "exit 0" in before_search, "команда продолжает работу после негодного шаблона"


def test_the_pattern_still_travels_as_an_argument():
    """🔴 ГРАНИЦА, КОТОРУЮ НЕЛЬЗЯ ПОТЕРЯТЬ. Шаблон приходит от модели, и подстановка его в
    команду — инъекция. Теперь он подставляется ДВАЖДЫ (проверка и поиск), поэтому
    проверяем оба места."""
    command = grep_command(ROOT, "a; rm -rf /", "")
    tokens = shlex.split(command)

    assert "rm" not in tokens, "шаблон разобрался как команда — это инъекция"
    assert command.count(shlex.quote("a; rm -rf /")) == 2, (
        "шаблон подставлен не в обе позиции: проверка и поиск разойдутся"
    )


def test_the_search_itself_is_unchanged():
    """⚠️ Починка не должна менять сам поиск: те же флаги, тот же потолок, тот же пропуск
    `.git` — иначе к одной находке добавится regression в другой."""
    command = grep_command(ROOT, "x", "", limit=42)

    assert "grep -rnI --exclude-dir=.git" in command
    assert "head -n 42" in command
