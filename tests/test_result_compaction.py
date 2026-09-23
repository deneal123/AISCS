"""Сжатие вывода инструмента: конец обязан выживать.

🔴 Главное утверждение: у вывода команды смысл в КОНЦЕ (код возврата, ошибка, итог), и
обрезка «первых N символов» выбрасывала ровно его. Тесты сформулированы как вопрос «дошёл
ли до модели итог», а не «уложились ли в потолок».
"""

from __future__ import annotations

from service.domain.tools.result_compaction import collapse_repeats, compact, head_and_tail


def _build_log(lines: int) -> str:
    return "\n".join(f"[12:00:{i:02d}] compiling module_{i}.py" for i in range(lines))


def test_the_end_survives_where_plain_truncation_lost_it() -> None:
    """🔴 Тот самый дефект: итог сборки не доезжал до модели вовсе."""
    text = _build_log(400) + "\nFAILED: 3 tests, exit code 1"
    compacted, lossy = compact(text, 500)
    assert lossy
    assert "exit code 1" in compacted, "конец вывода потерян — ради этого всё и делалось"
    assert text[:100] not in compacted or "compiling module_0" in compacted


def test_short_output_is_untouched_and_not_marked_lossy() -> None:
    compacted, lossy = compact("всё хорошо", 500)
    assert compacted == "всё хорошо" and not lossy


def test_no_limit_means_no_compaction() -> None:
    """Канонические чтения (файл) сжимать нельзя: там короткое = неверное."""
    text = "x" * 10_000
    assert compact(text, None) == (text, False)


def test_repeats_collapse_without_losing_anything() -> None:
    """Схлопнутый повтор — не потеря: содержимое строки осталось, ушли её дубликаты."""
    text = "\n".join(["Warning: deprecated"] * 40) + "\nDone"
    compacted, lossy = compact(text, 200)
    assert not lossy, "схлопывание повторов не должно считаться потерей"
    assert "×40" in compacted and "Done" in compacted


def test_repeats_are_matched_by_fingerprint_not_byte_for_byte() -> None:
    """⚠️ Строки лога различаются меткой времени: побайтовое сравнение не схлопнуло бы
    НИЧЕГО, то есть приём выглядел бы работающим и не работал."""
    text = "\n".join(f"[10:00:{i:02d}] waiting for lock" for i in range(20))
    assert "×20" in collapse_repeats(text)


def test_lines_differing_by_a_small_number_are_NOT_collapsed() -> None:
    """🔴 Обратная сторона отпечатка: «0 errors» и «3 errors» различаются ПО СУЩЕСТВУ.

    Нормализовать все числа было бы проще и опаснее — схлопнулись бы строки с разным
    итогом, и модель увидела бы одну вместо обеих.
    """
    text = "\n".join(["build ok", *[f"module {i}: {i} errors" for i in range(10)]])
    collapsed = collapse_repeats(text)
    assert "×" not in collapsed
    assert "9 errors" in collapsed and "0 errors" in collapsed


def test_a_few_lines_are_left_alone() -> None:
    """Короткий вывод схлопывать незачем — «×2» на двух строках только мешает читать."""
    text = "a\na\nb"
    assert collapse_repeats(text) == text


def test_head_and_tail_keeps_both_ends_and_says_how_much_is_gone() -> None:
    text = "НАЧАЛО" + "x" * 5000 + "КОНЕЦ"
    out = head_and_tail(text, 400)
    assert out.startswith("НАЧАЛО") and out.endswith("КОНЕЦ")
    assert "пропущено" in out
    assert len(out) <= 400, "маркер пропуска обязан ВХОДИТЬ в потолок, а не идти сверх него"


def test_tail_gets_the_larger_share() -> None:
    """Хвост важнее головы: там итог, а голова нужна лишь чтобы понять, что выполнялось."""
    text = "H" * 5000 + "T" * 5000
    out = head_and_tail(text, 1000)
    assert out.count("T") > out.count("H")


def test_result_never_exceeds_the_limit() -> None:
    for limit in (100, 500, 6000):
        compacted, _ = compact(_build_log(2000), limit)
        assert len(compacted) <= limit, f"потолок {limit} пробит: {len(compacted)}"
