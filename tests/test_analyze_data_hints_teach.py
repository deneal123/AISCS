"""Подсказки табличного инструмента ведут модель к данным, а не к файлу.

🔴 НАЙДЕНО ЗАМЕРОМ НА ЖИВОМ СТЕНДЕ (4 вопроса к `iris.csv`). Модель писала
`FROM read_csv_auto('iris.csv')` и `FROM 'iris.csv'`, получала от DuckDB

    Permission Error: Cannot access file "iris.csv" - file system operations are disabled

и пересказывала это человеку: «Возникла ошибка при попытке доступа к данным. Возможно,
проблема связана с настройками файловой системы». То есть вместо ответа по данным, лежащим
рядом, человек получал диагноз, которого не просил.

Две причины, обе в текстах:
* схема не говорила, что таблицы УЖЕ загружены и файлов нет;
* текст ошибки сообщал диагноз, но не следующий шаг.

⚠️ Соблазн усилился после того, как имя таблицы стало совпадать с именем файла (иначе
таблицы было не различить). Значит подсказка обязана быть явной — «похоже на файл, но не
файл» модель сама не выведет.
"""

from __future__ import annotations

from service.domain.tools.function_tools import _format_analyze_result

SCHEMA = {
    "tables": [
        {
            "name": "iris",
            "source": "iris.csv",
            "row_count": 150,
            "columns": [{"name": "species", "type": "VARCHAR"}],
            # ⚠️ Строки превью — СПИСКИ значений, не словари: `_md_table` режет их по индексу.
            # Двойник обязан повторять форму настоящих данных, иначе тест падает не о том.
            "preview": [["setosa"]],
        }
    ]
}


def _flat(text: str) -> str:
    """Смятые переносы: подсказки свёрстаны по ширине, и правило не должно зависеть от того,
    где оказался разрыв. На этом уже дважды краснели стражи промпта."""
    return " ".join(text.lower().split())


# --- схема: таблицы, а не файлы --------------------------------------------------------- #


def test_the_schema_says_tables_are_already_loaded():
    """🔴 ГЛАВНОЕ. Без этого модель обращается к файлу — замерено дважды."""
    flat = _flat(_format_analyze_result(SCHEMA, ""))

    assert "уже загружены" in flat, "не сказано, что данные уже в памяти"
    assert "файлов на диске нет" in flat, "не сказано, что файла не существует"


def test_the_schema_shows_a_working_example():
    """⚠️ Пример с НАСТОЯЩИМ именем таблицы: абстрактное «обращайся по имени» модель уже
    читала — и всё равно писала имя файла."""
    out = _format_analyze_result(SCHEMA, "")

    assert "`FROM iris`" in out, "нет готового примера обращения к таблице"


def test_the_schema_names_the_forbidden_forms():
    """⚠️ Обе формы, которые модель писала живьём, названы прямо."""
    flat = _flat(_format_analyze_result(SCHEMA, ""))

    assert "read_csv_auto" in flat, "файловая функция не названа запрещённой"
    assert "from 'файл.csv'" in flat, "обращение к файлу строкой не названо запрещённым"


def test_the_schema_still_lists_names_and_columns():
    """🔴 ГРАНИЦА: подсказка не должна вытеснить саму схему — по ней и пишется SQL."""
    out = _format_analyze_result(SCHEMA, "")

    assert "iris" in out and "species" in out and "150" in out
    assert "из «iris.csv»" in out, "не видно, из какого файла таблица"


def test_an_empty_table_list_does_not_crash_the_hint():
    """⚠️ Пример строится из первой таблицы: пустой список не должен ронять формат."""
    out = _format_analyze_result({"tables": []}, "")

    assert "analyze_data" in out


# --- ошибка обязана учить ---------------------------------------------------------------- #

FILE_ERROR = {
    "error": "sql_error",
    "detail": 'Permission Error: Cannot access file "iris.csv" - file system operations are '
    "disabled by configuration",
}


def test_a_file_access_error_explains_what_to_do():
    """🔴 «Настройки файловой системы» — это диагноз, а модель пересказала его человеку
    вместо ответа. Подсказка обязана давать СЛЕДУЮЩИЙ ШАГ."""
    flat = _flat(_format_analyze_result(FILE_ERROR, "SELECT * FROM 'iris.csv'"))

    assert "обратился к файлу" in flat, "причина не названа"
    assert "по имени из схемы" in flat, "не сказано, как исправить"
    assert "read_csv_auto" in flat, "не сказано, что именно убрать из запроса"


def test_the_original_detail_is_not_hidden():
    """⚠️ Подсказку добавляем, а не подменяем ею текст СУБД: без него не отладить."""
    out = _format_analyze_result(FILE_ERROR, "SELECT 1")

    assert "file system operations are disabled" in out


def test_an_ordinary_sql_error_keeps_the_plain_hint():
    """🔴 ГРАНИЦА. Опечатка в колонке — не файловая ошибка, и специальная подсказка про
    файлы тут только сбивала бы."""
    out = _format_analyze_result(
        {"error": "sql_error", "detail": 'Binder Error: Referenced column "spesies" not found'},
        "SELECT spesies FROM iris",
    )
    flat = _flat(out)

    assert "исправь запрос" in flat
    assert "обратился к файлу" not in flat, "подсказка про файлы приклеилась не к тому отказу"


def test_a_non_sql_failure_is_reported_as_itself():
    """⚠️ Сайдкар недоступен — это не «поправь SQL»: чинить нечего, и врать не надо."""
    flat = _flat(
        _format_analyze_result({"error": "sidecar_unavailable", "detail": "нет связи"}, "")
    )

    assert "не удалось выполнить запрос" in flat
    assert "исправь запрос" not in flat
