"""В песочницу едут ВСЕ файлы диалога, а не только те, что годятся для SQL.

🔴 Импорт шёл по ТАБЛИЧНОМУ списку: `build_engine_env(..., tabular_files)`. То есть
рабочий каталог содержал ровно то, что имеет смысл отдать в DuckDB, а приложенный
`.docx`/`.pdf`/`.py` в нём не появлялся вовсе. Снаружи это выглядело как «песочница не
берётся»: инструменты выдавались, каталог был пуст, и открыть в нём было нечего.

⚠️ После отбора таблиц ПО ФОРМЕ (`shared/tabular_shape.py`) круг ещё уже: словарь
`.json` из табличного списка выпал — и, будь импорт прежним, выпал бы и из песочницы.
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest

from service.models.key_value import ServiceType
from service.services.chat.infrastructure import agent_context as ac


class _Row:
    def __init__(self, fid, name, original=None):
        self.id, self.file_name, self.type = fid, name, ServiceType.CHAT
        # Имя, под которым файл прислал человек. У старых записей его нет — тогда
        # потребитель падает на basename ключа хранилища.
        self.original_name = original


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


@pytest.fixture
def storage(monkeypatch):
    """Диалог с таблицей, словарём `.json` и документом."""
    heads = {
        "uploads/CHAT/rows.csv": b"id,email\n1,a@b.c\n",
        "uploads/CHAT/config.json": json.dumps({"server": {"host": "x"}}).encode(),
        "uploads/CHAT/tz.docx": b"PK\x03\x04binary",
    }

    originals = {
        "uploads/CHAT/rows.csv": "таблица продаж.csv",
        "uploads/CHAT/config.json": "рассылка.json",
        "uploads/CHAT/tz.docx": "ТЗ на портал.docx",
    }

    class _Session:
        async def execute(self, _stmt):
            return _Result([_Row(k, k, originals[k]) for k in heads])

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Pg:
        def get_session_context(self):
            return _Ctx()

    class _FileService:
        async def get_file_head_by_key(self, *, file_key, max_bytes):
            return heads[file_key][:max_bytes]

        async def get_presigned_url_by_key(self, *, file_key):
            return f"https://storage/{file_key}"

    from service.services.chat.infrastructure.chat_worker import factory as fac

    monkeypatch.setattr(
        fac.ChatWorkerDependencyFactory, "create_pg_connector", lambda self, cfg: _Pg()
    )
    monkeypatch.setattr(fac, "build_file_service", lambda cfg, pg: _FileService())
    monkeypatch.setattr(ac, "resolve_user_uuid", lambda uid, anonymous_fallback=False: "u-1")
    return list(heads)


@pytest.mark.asyncio
async def test_dialog_list_carries_everything_the_person_attached(storage):
    """⚠️ ГЛАВНОЕ. Документ и словарь не пропадают из рабочего каталога."""
    out = await ac.list_user_dialog_file_links("user", file_ids=storage)

    assert sorted(item["name"] for item in out) == [
        "ТЗ на портал.docx",
        "рассылка.json",
        "таблица продаж.csv",
    ], "часть приложенных файлов в песочницу не попадёт — открывать будет нечего"


@pytest.mark.asyncio
async def test_files_keep_the_name_the_person_gave_them(storage):
    """🔴 НАЙДЕНО ЖИВЫМ ПРОГОНОМ. В каталоге были ключи хранилища, а не имена файлов.

    `uploads/CHAT/123f5c3b1a2a4c8cb6977fa42ec375d1.json` не говорит ни человеку в панели,
    ни модели в `ws_list`, ЧТО это за файл — при том что оба видят его как «приложенный».
    """
    out = await ac.list_user_dialog_file_links("user", file_ids=storage)

    assert not any("uploads/CHAT" in item["name"] for item in out), "в каталог уехал ключ хранилища"
    assert "рассылка.json" in {item["name"] for item in out}


@pytest.mark.asyncio
async def test_a_hostile_original_name_cannot_escape_the_directory(monkeypatch):
    """⚠️ Исходное имя приходит ОТ ПОЛЬЗОВАТЕЛЯ: `../../etc/passwd` в нём — обычное дело."""
    row = _Row("f1", "uploads/CHAT/x.json", "../../etc/passwd")

    assert ac._workspace_name(row, set()) == "passwd"


def test_colliding_names_are_separated():
    """Два `отчёт.xlsx` в одном диалоге: второй молча затёр бы первый."""
    taken: set[str] = set()
    first = ac._workspace_name(_Row("a", "uploads/CHAT/1.xlsx", "отчёт.xlsx"), taken)
    second = ac._workspace_name(_Row("b", "uploads/CHAT/2.xlsx", "отчёт.xlsx"), taken)

    assert first == "отчёт.xlsx"
    assert second == "отчёт (2).xlsx"


def test_record_without_an_original_name_falls_back_to_the_key():
    """Старые записи исходного имени не знают — выдумывать его нельзя."""
    assert ac._workspace_name(_Row("c", "uploads/CHAT/abc.json"), set()) == "abc.json"


@pytest.mark.asyncio
async def test_two_lists_differ_and_that_is_the_point(storage):
    """Таблицы — для SQL, песочница — для работы. Круги РАЗНЫЕ, и это не совпадение."""
    tabular, dialog = await ac.collect_thread_files(
        None, "t-1", "user", {"file_ids": storage}, has_new_file=True
    )

    assert [item["name"] for item in tabular] == ["uploads/CHAT/rows.csv"], (
        "в analyze_data уехало лишнее — словарь и документ в SQL не читаются"
    )
    assert len(dialog) == 3, "песочница получила урезанный список"


def test_worker_imports_the_dialog_list_not_the_tabular_one():
    """🔴 ТОЧКА ВЫЗОВА. `build_engine_env` обязан получать список ДИАЛОГА.

    Мутация «вернуть `tabular_files` четвёртым аргументом» обязана красить этот тест:
    сама функция ``list_user_dialog_file_links`` от такой подмены не пострадает и
    останется зелёной — ровно тот случай, когда поломка живёт в МЕСТЕ ВЫЗОВА.
    """
    # ⚠️ Сбор переехал в `chat_worker/turn_context.py` (вынос из разросшейся функции
    # воркера). Правило то же: в песочницу уезжает список ДИАЛОГА, а не табличный.
    from service.services.chat.infrastructure.chat_worker import turn_context as tc

    tree = ast.parse(inspect.getsource(tc.collect_engine_inputs))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_engine_env"
    ]
    assert calls, "песочница воркером не собирается вовсе"
    for call in calls:
        names = [a.id for a in call.args if isinstance(a, ast.Name)]
        assert "dialog_files" in names, (
            "в песочницу импортируется не список диалога — приложенный документ в "
            f"рабочем каталоге не появится (аргументы: {names})"
        )
        assert "tabular_files" not in names, "в песочницу снова уехал ТАБЛИЧНЫЙ список"
