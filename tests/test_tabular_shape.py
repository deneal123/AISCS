"""Таблица или словарь — решает ФОРМА СОДЕРЖИМОГО, а не расширение.

🔴 ЖИВОЙ ИНЦИДЕНТ. `А - рассылка.json` + «вычитай 10 строку» → «Табличный файл —
анализирую через SQL», два вызова `analyze_data`, ответ «десятой строки в загруженных
данных нет». `.json` стоял в списке табличных расширений и перекрывал выбор
оркестратора детерминированно.

Набор векторов «содержимое → вердикт»: массив записей, JSONL, обёртка, разнородные
объекты, дерево настроек, однострочный csv, проза в `.txt`, обрыв головы.
"""

from __future__ import annotations

import json

import pytest

from service.shared.tabular_shape import HEAD_BYTES, looks_tabular

# ── таблицы ───────────────────────────────────────────────────────────────────


def test_array_of_uniform_objects_is_table():
    """⚠️ ГЛАВНОЕ (положительная сторона). Массив записей — это таблица."""
    body = json.dumps([{"id": 1, "email": "a@b.c"}, {"id": 2, "email": "d@e.f"}])
    assert looks_tabular("рассылка.json", body.encode()) is True


def test_jsonl_of_objects_is_table():
    body = b'{"id": 1, "name": "a"}\n{"id": 2, "name": "b"}\n'
    assert looks_tabular("events.jsonl", body) is True
    assert looks_tabular("events.ndjson", body) is True


def test_wrapper_with_single_array_is_table():
    """Обёртка `{"data": [ … ]}` — таблица: массив один и он же тело файла."""
    body = json.dumps({"total": 2, "data": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]})
    assert looks_tabular("dump.json", body.encode()) is True


def test_mostly_matching_keys_still_a_table():
    """«В основном совпадающий набор ключей»: пропуск поля таблицу не отменяет."""
    body = json.dumps([{"a": 1, "b": 2}, {"a": 3}, {"a": 4, "b": 5}])
    assert looks_tabular("rows.json", body.encode()) is True


def test_csv_with_rows_is_table():
    assert looks_tabular("data.csv", b"id,email\n1,a@b.c\n2,d@e.f\n") is True


def test_binary_formats_trusted_by_container():
    """xlsx/parquet — таблица и есть контейнер, головы не требуется."""
    assert looks_tabular("report.xlsx", None) is True
    assert looks_tabular("part.parquet", None) is True


def test_truncated_array_head_still_a_table():
    """🔴 Голова обрывается ПОСРЕДИ ЭЛЕМЕНТА — это НОРМА, а не «не разобралось».

    Иначе любой большой датасет уезжал бы читаться текстом: json.loads на обрезанной
    голове падает всегда.

    ⚠️ Записи нарочно ЖИРНЫЕ: при мелких в голову влезает больше элементов, чем мы
    вообще пробуем, обрыв не наступает — и тест зеленел бы, не проверив обрыв.
    """
    row_chars = HEAD_BYTES // 6
    rows = [{"id": i, "text": "x" * row_chars} for i in range(40)]
    head = json.dumps(rows).encode()[:HEAD_BYTES]
    assert head[-1:] not in (b"}", b"]"), "голова обязана рваться посреди записи"
    assert looks_tabular("big.json", head) is True


def test_delimited_txt_is_table():
    """`.txt` с одинаковым числом разделителей — всё-таки таблица."""
    body = b"id\tname\tsum\n1\ta\t10\n2\tb\t20\n"
    assert looks_tabular("export.txt", body) is True


# ── словари ───────────────────────────────────────────────────────────────────


def test_settings_tree_is_not_a_table():
    """⚠️ ГЛАВНОЕ. Дерево настроек — не таблица, читается текстом."""
    body = json.dumps(
        {"server": {"host": "localhost", "port": 8080}, "debug": True, "tags": ["a", "b"]}
    )
    assert looks_tabular("config.json", body.encode()) is False


def test_heterogeneous_objects_are_not_a_table():
    """Массив разнородных объектов: общей части ключей нет — в SQL ему нечего делать."""
    body = json.dumps([{"a": 1}, {"b": 2}, {"c": 3}])
    assert looks_tabular("mixed.json", body.encode()) is False


def test_array_of_scalars_is_not_a_table():
    assert looks_tabular("ids.json", b"[1, 2, 3, 4]") is False


def test_wrapper_with_two_arrays_is_ambiguous():
    """Два массива записей в обёртке — неоднозначно, значит словарь."""
    body = json.dumps({"users": [{"a": 1}, {"a": 2}], "orders": [{"b": 1}, {"b": 2}]})
    assert looks_tabular("dump.json", body.encode()) is False


def test_wrapper_with_nested_tree_is_not_a_table():
    body = json.dumps({"meta": {"author": "x", "ts": 1}, "rows": [{"a": 1}, {"a": 2}]})
    assert looks_tabular("dump.json", body.encode()) is False


def test_broken_json_is_a_dictionary():
    """Не распарсилось → словарь: «прочитал текстом» дешевле, чем «строки нет»."""
    assert looks_tabular("broken.json", b"{ not json at all") is False


def test_single_line_csv_is_not_a_table():
    """🔴 Один заголовок без строк — не таблица: SQL по нему всегда пуст."""
    assert looks_tabular("empty.csv", b"id,email\n") is False


def test_prose_txt_is_not_a_table():
    """Проза в `.txt` — не таблица, хотя DuckDB и прочитал бы её как CSV."""
    body = "Договор оказания услуг.\nСтороны договорились о следующем.\nПункт первый.\n"
    assert looks_tabular("dogovor.txt", body.encode()) is False


def test_jsonl_of_scalars_is_not_a_table():
    assert looks_tabular("log.jsonl", b'"first"\n"second"\n') is False


def test_unreadable_head_of_json_is_a_dictionary():
    """Содержимое недоступно — судить не по чему; вера имени `.json` вернула бы дефект."""
    assert looks_tabular("рассылка.json", None) is False
    assert looks_tabular("notes.txt", None) is False


def test_unreadable_head_of_csv_keeps_the_declaration():
    """А вот `.csv` объявляет данные сам: недоступное хранилище не повод терять таблицу."""
    assert looks_tabular("data.csv", None) is True


def test_unknown_extension_is_never_tabular():
    assert looks_tabular("photo.png", b"\x89PNG") is False


# ── подключение к потоку ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_json_dictionary_never_becomes_a_table_link(monkeypatch):
    """⚠️ ТОЧКА ВЫЗОВА, живой кадр целиком: словарь `.json` не доезжает до `analyze_data`.

    Правило, которое никто не вызывает, не чинит ничего — поэтому проверяем ту самую
    функцию, что собирает ссылки для инструмента, а не только классификатор.
    """
    from service.models.key_value import ServiceType
    from service.services.chat.infrastructure import agent_context as ac
    from service.services.chat.infrastructure.chat_worker import factory as fac

    heads = {
        "uploads/CHAT/рассылка.json": json.dumps({"smtp": {"host": "mx"}, "retries": 3}).encode(),
        "uploads/CHAT/rows.json": json.dumps([{"a": 1, "b": 2}, {"a": 3, "b": 4}]).encode(),
    }

    class _Row:
        def __init__(self, fid, name):
            self.id, self.file_name, self.type = fid, name, ServiceType.CHAT

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _Session:
        async def execute(self, _stmt):
            return _Result([_Row(k, k) for k in heads])

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

    monkeypatch.setattr(
        fac.ChatWorkerDependencyFactory, "create_pg_connector", lambda self, cfg: _Pg()
    )
    monkeypatch.setattr(fac, "build_file_service", lambda cfg, pg: _FileService())
    monkeypatch.setattr(ac, "resolve_user_uuid", lambda uid, anonymous_fallback=False: "u-1")

    out = await ac.list_user_tabular_file_links("user", file_ids=list(heads))

    assert [item["name"] for item in out] == ["uploads/CHAT/rows.json"], (
        "словарь `.json` уехал в analyze_data — SQL снова ответит «десятой строки нет»"
    )


def test_wired_into_upload_response():
    """Клиент получает вердикт о форме — от него зависит модальность вложения."""
    import inspect

    from service.services.chat.application.use_cases import upload_file_use_case as uc

    src = inspect.getsource(uc.UploadFileUseCase.execute)
    assert '"is_tabular": looks_tabular(' in src, "аплоад не сообщает клиенту форму файла"

    from service.services.chat.presentation.routers.chat_api.schemas import UploadFileResponse

    assert "is_tabular" in UploadFileResponse.model_fields, "признак не доедет через схему ответа"
