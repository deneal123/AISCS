"""ЗАМЕР сжатия на эталонных выводах: что именно уцелело.

🔴 Правило то же, что с промптами: сжатие МЕНЯЕТ то, что видит модель, и «экономия» легко
оказывается потерей той самой строки, ради которой инструмент и звали. Поэтому здесь не
проверка «влезло в потолок» (это уже есть рядом), а проверка СОДЕРЖАНИЯ: на реалистичных
выводах pytest, npm и git обязаны уцелеть причина провала и итог.

⚠️ Эталоны собраны из настоящей формы вывода этих команд, а не выдуманы: у pytest итог —
полоса `=== N failed ===`, у npm причина в строках `npm ERR!`, у git — `CONFLICT`.
"""

from __future__ import annotations

from service.domain.tools.result_compaction import compact_with_report

LIMIT = 1200


def _pytest_output() -> str:
    """Прогон с покрытием: провал В СЕРЕДИНЕ, а хвост занят таблицей coverage.

    🔴 Так и выглядит настоящий `pytest --cov`, и ровно этот случай «голова+хвост» не
    спасает: в голове заголовок сессии, в хвосте таблица покрытия, а `FAILED` и причина
    остаются посередине. Эталон с провалом В КОНЦЕ зеленел бы и БЕЗ спасения значимых
    строк — то есть проверял бы не то (проверено мутацией).
    """
    head = "============================= test session starts =============================\n"
    head += "platform linux -- Python 3.13.1, pytest-8.4.2\ncollected 412 items\n\n"
    noise = "\n".join(f"tests/test_module_{i}.py ....... [ {i * 100 // 412}%]" for i in range(200))
    middle = (
        "\ntests/test_billing.py F                                              [ 51%]\n\n"
        "________________________ test_credits_are_charged _____________________________\n"
        "    assert charged == 42\n"
        "AssertionError: assert 0 == 42\n"
        "FAILED tests/test_billing.py::test_credits_are_charged - AssertionError\n"
    )
    more = "\n".join(f"tests/test_other_{i}.py ....... [ {50 + i // 8}%]" for i in range(200))
    coverage = "\n".join(
        f"service/module_{i}.py            {100 + i}     {i % 7}    9{i % 10}%" for i in range(200)
    )
    return (
        head
        + noise
        + middle
        + more
        + "\n---------- coverage: platform linux ----------\nName  Stmts  Miss  Cover\n"
        + coverage
        + "\nTOTAL                            41200   1337    97%\n"
    )


def _npm_output() -> str:
    """Причина В СЕРЕДИНЕ: после неё npm печатает ещё сотни строк тайминга и аудита."""
    noise = "\n".join(f"npm info run build {i} files processed" for i in range(200))
    error = (
        "\nnpm ERR! code ELIFECYCLE\n"
        "npm ERR! errno 2\n"
        "npm ERR! app@1.0.0 build: `webpack --mode production`\n"
    )
    after = "\n".join(f"npm timing reify:audit:{i} Completed in {i}ms" for i in range(200))
    return (
        "> app@1.0.0 build\n> webpack --mode production\n"
        + noise
        + error
        + after
        + "\nnpm notice A new release of npm is available\n"
    )


def _git_output() -> str:
    """Конфликт В СЕРЕДИНЕ: git продолжает сливать остальные файлы и после него."""
    before = "\n".join(f"Auto-merging src/module_{i}.py" for i in range(200))
    after = "\n".join(f"Auto-merging tests/test_{i}.py" for i in range(200))
    return (
        before
        + "\nCONFLICT (content): Merge conflict in src/billing.py\n"
        + after
        + "\nAutomatic merge failed; fix conflicts and then commit the result.\n"
    )


def test_pytest_failure_and_summary_survive():
    """⚠️ ГЛАВНОЕ. Ради чего звали `ws_run` — узнать, ЧТО упало и чем кончилось."""
    out, report = compact_with_report(_pytest_output(), LIMIT)

    assert "FAILED tests/test_billing.py::test_credits_are_charged" in out, (
        "потеряна строка провала — модель не узнает, ЧТО именно упало"
    )
    assert report["lossy"] is True
    assert len(out) <= LIMIT + len("\n⟨значимые строки из пропущенного⟩\n") + LIMIT


def test_npm_error_lines_survive():
    out, _report = compact_with_report(_npm_output(), LIMIT)

    assert "npm ERR! code ELIFECYCLE" in out, "причина провала сборки потеряна целиком"


def test_git_conflict_survives():
    out, _report = compact_with_report(_git_output(), LIMIT)

    assert "CONFLICT (content): Merge conflict in src/billing.py" in out


def test_report_says_what_was_applied():
    """⚠️ Незаметно урезанный вывод неотличим от неполного ответа инструмента."""
    _out, report = compact_with_report(_pytest_output(), LIMIT)

    assert "head_tail" in report["applied"]
    assert "salvage" in report["applied"], "значимые строки не спасались вовсе"
    assert report["before"] > report["after"] > 0


def test_nothing_is_reported_when_nothing_was_done():
    _out, report = compact_with_report("короткий вывод", LIMIT)

    assert report["applied"] == [] and report["lossy"] is False


def test_salvage_takes_the_LAST_matches_not_the_first():
    """У длинного прогона ранние ошибки часто вторичны — решает та, что ближе к итогу."""
    text = "\n".join(
        ["ERROR: каскадная ошибка номер один"]
        + [f"обычная строка лога {i}" for i in range(400)]
        + ["ERROR: настоящая причина в конце"]
    )

    out, _report = compact_with_report(text, 400)

    assert "настоящая причина в конце" in out


def test_output_without_anything_significant_is_not_padded():
    """Нет значимых строк — нет и заголовка о них: пустая рамка съедала бы бюджет."""
    text = "\n".join(f"просто строка вывода номер {i}" for i in range(400))

    out, report = compact_with_report(text, LIMIT)

    assert "значимые строки" not in out
    assert "salvage" not in report["applied"]


def test_dedup_alone_can_avoid_any_loss():
    """Повторы схлопнулись и всё влезло — потери НЕТ, и отчёт это говорит."""
    text = "\n".join(["одинаковая строка прогресса"] * 400) + "\nготово"

    out, report = compact_with_report(text, LIMIT)

    assert report["lossy"] is False
    assert report["applied"] == ["dedup"]
    assert "готово" in out
