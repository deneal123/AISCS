"""Раздувание контекста tool-loop: три рычага, каждый бьёт по своей части 89k.

⚠️ РЕАЛЬНЫЙ ИНЦИДЕНТ. Пользователь загрузил xlsx на 22 строки и попросил анализ. Запрос
ушёл в GigaChat с prompt=89 537 токенов, completion=1467 — при цене 22 751 кредит (~72₽).
89k — это не размер одного промпта, а СУММА prompt по ~5 вызовам в цикле инструментов:
`_merge_usage` складывает usage раундов (правильно — провайдер тарифицирует каждый), а
каждый раунд переотправляет весь растущий диалог. Три множителя наложились:

1. текст табличного файла вложен в промпт (~14k) И переотправляется каждый раунд, хотя
   файл едет ещё и таблицей для analyze_data — сырой текст модели не нужен;
2. результат инструмента (11 813 символов) не обрезался — множился по раундам;
3. до 9 вызовов LLM (max_turns=8), каждый с полной базой.

Тесты фиксируют каждый рычаг отдельно.
"""

from __future__ import annotations

from datetime import UTC, datetime

from service.domain.capabilities.tool_registry import tool_result_limit
from service.domain.runners import tool_loop as chat_runner
from service.domain.subagents.general import GeneralAgent
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


# --------------------------------------------------------------------------- #
# A2: результат инструмента обрезается перед возвратом в модель                 #
# --------------------------------------------------------------------------- #
def test_tool_result_is_trimmed():
    """⚠️ Большой результат режется — иначе он множится по раундам tool-loop."""
    huge = "x" * 20_000

    trimmed, _report = chat_runner._trim_tool_result(huge, "analyze_data")

    assert len(trimmed) < len(huge), "результат не обрезан — уедет целиком в каждый раунд"
    assert len(trimmed) <= tool_result_limit("analyze_data") + len(
        chat_runner._TOOL_TRUNCATION_NOTE
    )
    assert "усеч" in trimmed, "усечение не помечено — модель примет обрубок за полный ответ"


def test_small_tool_result_is_untouched():
    """⚠️ Короткий результат не трогаем: пометка на нём была бы ложью."""
    small = "схема: 3 колонки, 22 строки"

    assert chat_runner._trim_tool_result(small, "analyze_data")[0] == small


def test_trim_handles_empty():
    assert chat_runner._trim_tool_result("", "analyze_data")[0] == ""
    assert chat_runner._trim_tool_result(None, "analyze_data")[0] == ""


# --------------------------------------------------------------------------- #
# A3: потолок tool-раундов снижен                                              #
# --------------------------------------------------------------------------- #
def test_general_agent_caps_tool_rounds_low():
    """⚠️ max_turns снижен: каждый раунд переотправляет всю базу промпта.

    Значение проверяем через объект, а не константу в тесте — иначе тест и код
    держали бы каждый свою копию числа.
    """
    agent = GeneralAgent({"model": "test-model"})

    assert agent.max_turns <= 4, (
        f"max_turns={agent.max_turns}: цикл инструментов даёт до {agent.max_turns + 1} "
        "вызовов LLM, каждый с полной базой промпта — квадратичный рост стоимости"
    )


# --------------------------------------------------------------------------- #
# A1: табличный файл не вкладывается в промпт текстом                          #
# --------------------------------------------------------------------------- #
# A1: табличный файл не вкладывается в промпт текстом                          #
# --------------------------------------------------------------------------- #
from types import SimpleNamespace  # noqa: E402

from service.application.processor_steps import _files_for_prompt  # noqa: E402


def test_tabular_file_text_is_not_inlined():
    """⚠️ ГЛАВНЫЙ РЫЧАГ: файл едет таблицей → его текст в промпт не кладём."""
    ctx = SimpleNamespace(tabular_files=[{"name": "t1.csv", "url": "http://x/t1.csv"}])

    raw = "СЫРОЙ ТЕКСТ ТАБЛИЦЫ " * 500
    files, skipped = _files_for_prompt(ctx, raw)

    assert "СЫРОЙ ТЕКСТ ТАБЛИЦЫ" not in files, (
        "текст табличного файла вложен в промпт, хотя файл едет таблицей — те самые ~14k "
        "токенов, что множатся по раундам tool-loop"
    )
    assert len(files) < len(raw) / 20, "пометка разрослась — размен, ради которого резали, потерян"
    assert skipped is True, "срез не отмечен — некому будет показать пользователю статус"


def test_model_is_told_the_table_exists():
    """🔴 ЖИВАЯ ЖАЛОБА: «что по таблице?» → «ты пока не загрузил таблицу, прикрепи файл».

    Текст таблицы из промпта вырезан правильно, а ВЗАМЕН не клали ничего — в запросе не
    было ни слова о вложении, и модель делала единственный вывод, какой из него следует.
    Тот же дефект, что чинила инструкция к карте репозитория, только для другого типа
    вложения.
    """
    ctx = SimpleNamespace(tabular_files=[{"name": "База форума.xlsx", "url": "http://x"}])

    files, _ = _files_for_prompt(ctx, "СЫРОЙ ТЕКСТ ТАБЛИЦЫ")

    assert "База форума.xlsx" in files, "модель не знает, что файл приложен, и попросит его снова"
    assert "analyze_data" in files, "не сказано, чем читать таблицу"


def test_notice_is_wired_into_the_assembled_context():
    """🔴 ТОЧКА ВЫЗОВА: пометка обязана уехать в секцию `files` сборки контекста.

    ⚠️ Держать одну функцию мало: она может вернуть верную строку, а место вызова —
    передать в сборку пустоту, и все тесты выше останутся зелёными при том же дефекте.
    """
    import inspect

    from service.application import processor_context

    src = inspect.getsource(processor_context.build_context_step)

    assert "files_for_prompt, skipped_tabular = _files_for_prompt(" in src
    assert "files=files_for_prompt" in src, "в сборку контекста уходит не результат отбора"


def test_non_tabular_file_text_is_still_inlined():
    """⚠️ Обратная сторона: без таблиц текст файла вкладываем как раньше.

    Иначе «резать всё» сломало бы обычные документы (pdf/docx), которым analyze_data
    не поможет — ответ вышел бы без содержимого документа.
    """
    ctx = SimpleNamespace(tabular_files=None)

    files, skipped = _files_for_prompt(ctx, "ТЕКСТ PDF-ДОКУМЕНТА")

    assert files == "ТЕКСТ PDF-ДОКУМЕНТА"
    assert skipped is False


def test_empty_file_context_with_tabular_is_not_flagged():
    """Таблица есть, но текста файла нет — резать нечего, статус не шлём.

    🔴 А вот пометка нужна ВСЁ РАВНО. Клиент мог не прислать текст вовсе (xlsx не
    извлёкся, извлечение отвалилось), и привязка пометки к факту среза оставила бы модель
    без единого упоминания о файле — ровно тот случай, из-за которого всё и чинится.
    """
    ctx = SimpleNamespace(tabular_files=[{"name": "t.csv", "url": "u"}])

    files, skipped = _files_for_prompt(ctx, "")

    assert "t.csv" in files, "текста не было — и про файл модели не сказали"
    assert skipped is False


# --------------------------------------------------------------------------- #
# Смешанные вложения: документ/репозиторий РЯДОМ с таблицей не выбрасывается
# --------------------------------------------------------------------------- #
#
# 🔴 ЖИВОЙ ИНЦИДЕНТ. Пользователь приложил .json-датасет + .zip-репозиторий и попросил
# ревью КОДА. .json сделал tabular_files непустым, и оптимизация A1 выбросила ВЕСЬ
# file_context — вместе с картой репозитория, которой в analyze_data нет. Агент ответил
# «вставьте код». Признак «рядом есть нетабличный файл» ставит backend (знает типы).


def test_mixed_attachment_keeps_file_context():
    """⚠️ ГЛАВНОЕ. Таблица + документ → file_context (карта репо/PDF) НЕ выбрасывается."""
    ctx = SimpleNamespace(
        tabular_files=[{"name": "data.json", "url": "http://x"}],
        has_non_tabular_attachment=True,
    )

    files, skipped = _files_for_prompt(ctx, "# Карта репозитория\n## driver.py\ndef handle(): ...")

    assert files.startswith("# Карта репозитория"), (
        "карта репо выброшена из-за соседнего .json — агент не увидит код"
    )
    assert skipped is False


def test_pure_tabular_still_drops_context():
    """Без нетабличного вложения поведение прежнее: табличный текст режется (он в SQL)."""
    ctx = SimpleNamespace(
        tabular_files=[{"name": "data.json", "url": "http://x"}],
        has_non_tabular_attachment=False,
    )

    files, skipped = _files_for_prompt(ctx, "СЫРОЙ ТЕКСТ ТАБЛИЦЫ " * 100)

    assert "СЫРОЙ ТЕКСТ ТАБЛИЦЫ" not in files and skipped is True


def test_flag_absent_defaults_to_dropping():
    """Старый контекст без поля (getattr → False) режет как раньше — обратная совместимость."""
    ctx = SimpleNamespace(tabular_files=[{"name": "t.csv", "url": "u"}])  # нет has_non_tabular

    files, skipped = _files_for_prompt(ctx, "текст таблицы")

    assert "текст таблицы" not in files and skipped is True
