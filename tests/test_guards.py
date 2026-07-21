"""Гарды сайдкара duckdb: песочница SQL и санитизация имени таблицы.

Сервис исполняет SQL, который пишет МОДЕЛЬ, по файлам, которые прислал
ПОЛЬЗОВАТЕЛЬ. До этого файла тестов у него не было ни одного.

Самый важный тест здесь — `test_sql_cannot_read_the_filesystem`. Раньше отключение
внешнего доступа стояло внутри `try/except: pass`, и переименование настройки в новой
версии DuckDB убрало бы песочницу совершенно молча; теперь отказ поднимается наверх, а
факт закрытия проверяется чтением значения — см. `core._seal_external_access` и
`test_seal_raises_when_setting_is_gone` ниже.
"""

from __future__ import annotations

import base64

import duckdb
import pytest

import core
from core import run_query, table_name_for


def _file(name: str, content: str) -> dict:
    return {"name": name, "content_b64": base64.b64encode(content.encode()).decode()}


SALES = _file("sales.csv", "product,amount\nwidget,10\ngadget,20\n")

# Содержимое «постороннего» файла для проверки песочницы: он лежит на диске рядом,
# заведомо существует и корректно разбирается как CSV — значит единственная причина,
# по которой запрос может упасть, это закрытый доступ к файловой системе.
SECRET_CSV = "col\nsensitive-value\n"


# --------------------------------------------------------------------------- #
# Песочница                                                                    #
# --------------------------------------------------------------------------- #
def test_sql_cannot_read_the_filesystem(tmp_path):
    """SQL от модели не должен добираться до файлов контейнера.

    ⚠️ Файл создаётся РЯДОМ и заведомо существует. Первая версия теста читала
    `/etc/passwd`, и это было ложным гардом: при снятой песочнице три случая из
    четырёх всё равно падали — на Windows такого файла просто нет, а `read_csv`
    спотыкался на разборе. Тест «проходил», не проверяя ничего. Чтобы ошибка
    означала ИМЕННО закрытый доступ, читаемое должно существовать и разбираться.
    """
    secret = tmp_path / "secret.csv"
    secret.write_text(SECRET_CSV, encoding="utf-8")
    sql = f"SELECT * FROM read_csv_auto('{secret.as_posix()}')"

    with pytest.raises(duckdb.Error):
        run_query(sql, [SALES], 10)


def test_seal_raises_when_setting_is_gone():
    """Если настройка песочницы исчезла — прогон обязан УПАСТЬ, а не продолжиться.

    Имитируем именно тот сценарий, ради которого гард и существует: новая версия
    DuckDB не знает `enable_external_access`. Прежний `except: pass` проглотил бы
    это и выполнил SQL от модели по незапечатанному соединению.
    """

    class _ConWithoutSetting:
        def execute(self, sql):
            raise RuntimeError("Catalog Error: unrecognized configuration parameter")

    with pytest.raises(RuntimeError, match="внешний доступ"):
        core._seal_external_access(_ConWithoutSetting())


def test_seal_raises_when_setting_did_not_take_effect():
    """И если `SET` прошёл, но значение осталось открытым — тоже падаем.

    Ловит молчаливое игнорирование неизвестной настройки: `SET` не бросил, а
    доступ остался. Проверка значением отличает «применилось» от «не возразило».
    """

    class _ConIgnoringSet:
        def execute(self, sql):
            return self

        def fetchone(self):
            return (True,)

    with pytest.raises(RuntimeError, match="остался открыт"):
        core._seal_external_access(_ConIgnoringSet())


def test_sandbox_test_is_not_vacuous(tmp_path):
    """Контроль: тот же файл ЧИТАЕТСЯ, если запретить доступ забыли.

    Без этой проверки предыдущий тест нельзя отличить от «SQL всегда падает».
    Здесь песочница отключается намеренно — и данные должны прийти.
    """
    secret = tmp_path / "secret.csv"
    secret.write_text(SECRET_CSV, encoding="utf-8")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(f"SELECT * FROM read_csv_auto('{secret.as_posix()}')").fetchall()
    finally:
        con.close()

    assert rows == [("sensitive-value",)], "файл должен читаться без песочницы"


def test_loaded_tables_are_still_queryable():
    """Обратная сторона: песочница не должна ломать нормальную работу."""
    out = run_query("SELECT sum(amount) AS total FROM sales", [SALES], 10)

    assert out["rows"] == [[30]]
    assert out["columns"] == ["total"]


# --------------------------------------------------------------------------- #
# Имя файла → SQL-идентификатор                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "filename",
    [
        'a";DROP TABLE t;--.csv',
        "../../etc/passwd.csv",
        "1sales.csv",
        "продажи.csv",
        "with space.csv",
        "a'b.csv",
        ".csv",
    ],
)
def test_table_name_is_always_a_safe_identifier(filename):
    """Результат подставляется в SQL f-строкой — это и есть поверхность инъекции."""
    import re

    name = table_name_for(filename, set())

    assert re.fullmatch(r"[a-z_][a-z0-9_]*", name), f"{filename!r} → небезопасное имя {name!r}"


def test_colliding_names_get_unique_suffixes():
    used: set[str] = set()
    first = table_name_for("data.csv", used)
    second = table_name_for("data.csv", used)

    assert first != second


def test_injection_through_filename_does_not_execute():
    """Сквозная проверка: файл с SQL в имени грузится как обычная таблица."""
    evil = _file('x";DROP TABLE sales;--.csv', "a\n1\n")

    out = run_query("", [SALES, evil], 10)

    names = [t["name"] for t in out["tables"]]
    assert len(names) == 2 and all(n.replace("_", "").isalnum() for n in names), names


# --------------------------------------------------------------------------- #
# Потолок строк                                                                #
# --------------------------------------------------------------------------- #
def test_max_rows_is_clamped_to_hard_limit(monkeypatch):
    """`max_rows` приходит из запроса: без клампа модель могла бы вытянуть всё."""
    monkeypatch.setattr(core, "HARD_MAX_ROWS", 2)
    rows = _file("many.csv", "n\n" + "\n".join(str(i) for i in range(10)) + "\n")

    out = run_query("SELECT * FROM many", [rows], 1000)

    assert out["row_count"] == 2
    assert out["truncated"] is True


def test_empty_sql_returns_schema_preview():
    """Пустой SQL — это разведка: схема и превью, чтобы модель писала запрос осознанно."""
    out = run_query("", [SALES], 10)

    assert out["sql"] == "" and out["rows"] == []
    assert out["tables"] and out["tables"][0]["name"] == "sales"


def test_unsupported_extension_is_refused():
    out_of_scope = _file("payload.exe", "MZ")

    with pytest.raises(ValueError):
        run_query("SELECT 1", [out_of_scope], 10)
