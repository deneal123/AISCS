"""«В сообщении есть таблица» — свойство ДИАЛОГА, а не аккаунта.

⚠️ ЖИВОЙ ИНЦИДЕНТ. Пользователь приложил PDF-техзадание и попросил его разобрать. Агент
ответил «уточни, что нужно сделать»: промпт основного вызова — 1 606 токенов, содержимого
документа ноль. Файл при этом лежал в хранилище, парсер извлекал из него 16 076 символов.

Причина оказалась не в PDF. ``list_user_tabular_file_links`` выбирала файлы по ОДНОМУ
``user_id`` — то есть всё, что пользователь загружал когда-либо. У него с 11 и 13 июля
лежали два ``.json`` из посторонних тредов, а ``.json`` входит в табличные расширения.
Список получался непустым, движок (`_files_for_prompt` в сайдкаре) читал это как «в
сообщении таблица, текст вкладывать не надо — его посмотрит analyze_data через SQL» и
выбрасывал текст PDF из промпта. Один ``.csv``, загруженный однажды, ломал так КАЖДОЕ
последующее сообщение с документом — навсегда и молча.

Отсюда два инварианта, которые и стерегут тесты ниже:
* выборка ограничена файлами текущего диалога (``file_ids``), а пустой список значит
  «таблиц нет», а не «фильтра нет»;
* набор файлов диалога живёт по треду с той же семантикой, что и текст вложения: новый
  файл в сообщении ЗАМЕЩАЕТ прежний набор (в том числе обнуляет его), а follow-up без
  вложения — донашивает.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from service.services.chat.infrastructure import agent_context as ac


class _Row:
    def __init__(self, file_id: str, name: str):
        self.id = file_id
        self.file_name = name
        from service.models.key_value import ServiceType

        self.type = ServiceType.CHAT


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    async def execute(self, _stmt):
        self._calls.append("execute")
        return _Result(self._rows)


class _Ctx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class _Pg:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def get_session_context(self):
        return _Ctx(_Session(self._rows, self._calls))


class _FileService:
    async def get_presigned_url_by_key(self, *, file_key):
        return f"https://storage/{file_key}"


@pytest.fixture
def storage(monkeypatch):
    """Хранилище с ДВУМЯ табличными файлами: свежий из диалога и давний посторонний."""
    calls: list[str] = []
    rows = [
        _Row("fresh-1", "uploads/CHAT/aaa.csv"),
        _Row("stale-9", "uploads/CHAT/bbb.json"),  # 12 дней назад, другой тред
        _Row("doc-2", "uploads/CHAT/ccc.pdf"),  # не табличный вовсе
    ]
    from service.services.chat.infrastructure.chat_worker import factory as fac

    monkeypatch.setattr(
        fac.ChatWorkerDependencyFactory, "create_pg_connector", lambda self, cfg: _Pg(rows, calls)
    )
    monkeypatch.setattr(fac, "build_file_service", lambda cfg, pg: _FileService())
    monkeypatch.setattr(ac, "resolve_user_uuid", lambda uid, anonymous_fallback=False: "u-1")
    return calls


@pytest.mark.asyncio
async def test_stale_file_from_another_thread_is_not_tabular(storage):
    """⚠️ ГЛАВНОЕ. Давний .json не должен превращать сообщение в «запрос по таблице».

    Ровно этот случай и был в проде: пользователь прислал PDF, а решение о том, что у
    него таблица, принимали два .json из тредов двенадцатидневной давности.
    """
    out = await ac.list_user_tabular_file_links("user", file_ids=["fresh-1"])

    names = [item["name"] for item in out]
    assert names == ["uploads/CHAT/aaa.csv"], (
        f"в табличные файлы диалога попало лишнее: {names} — движок выбросит текст "
        "вложения из промпта, и агент останется без документа"
    )


@pytest.mark.asyncio
async def test_no_files_in_dialog_means_no_tables(storage):
    """Пустой список идентификаторов — это «таблиц нет», а не «фильтра нет».

    Разница принципиальная: трактовка «фильтра нет» возвращала бы весь аккаунт, то есть
    в точности прежний баг. Заодно проверяем, что в БД не ходим вовсе.
    """
    out = await ac.list_user_tabular_file_links("user", file_ids=[])

    assert out == []
    assert storage == [], "сходили в БД, хотя в диалоге нет ни одного файла"


@pytest.mark.asyncio
async def test_pdf_alone_yields_no_tabular_files(storage):
    """Приложен один PDF → таблиц нет, текст вложения обязан доехать до промпта."""
    out = await ac.list_user_tabular_file_links("user", file_ids=["doc-2"])

    assert out == [], "PDF посчитали табличным — его текст выбросят из промпта"


@pytest.mark.asyncio
async def test_new_attachment_replaces_thread_set(monkeypatch):
    """Новый файл в сообщении ЗАМЕЩАЕТ набор диалога — как и текст вложения.

    Иначе таблица из первого сообщения «прилипала» бы к треду и продолжала подавлять
    текст всех следующих документов.
    """
    store: dict = {}

    class _Redis:
        def get(self, key):
            return store.get(key)

        def set(self, key, value, ex=None):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

    out = await ac._recall_or_persist_thread_tabular(
        _Redis(), "t-1", ["fresh-1"], has_new_file=True
    )
    assert out == ["fresh-1"]

    # Следующим сообщением приложен PDF — таблиц в диалоге больше нет.
    out = await ac._recall_or_persist_thread_tabular(_Redis(), "t-1", ["doc-2"], has_new_file=True)
    assert out == ["doc-2"], "набор диалога не обновился новым вложением"


@pytest.mark.asyncio
async def test_followup_without_attachment_keeps_the_table():
    """Follow-up без вложения («а сколько там строк») не теряет таблицу диалога."""
    store = {"chat:t-1:file_ids": '["fresh-1"]'}

    class _Redis:
        def get(self, key):
            return store.get(key)

        def set(self, key, value, ex=None):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

    out = await ac._recall_or_persist_thread_tabular(_Redis(), "t-1", None, has_new_file=False)

    assert out == ["fresh-1"], "таблица диалога потеряна на follow-up — analyze_data ослепнет"


@pytest.mark.asyncio
async def test_attachment_without_files_clears_the_table():
    """Приложили НЕ файл (картинка/аудио без file_ids) → прежняя таблица не воскресает."""
    store = {"chat:t-1:file_ids": '["fresh-1"]'}

    class _Redis:
        def get(self, key):
            return store.get(key)

        def set(self, key, value, ex=None):
            store[key] = value

        def delete(self, key):
            store.pop(key, None)

    out = await ac._recall_or_persist_thread_tabular(_Redis(), "t-1", [], has_new_file=True)

    assert out == []
    assert "chat:t-1:file_ids" not in store, "устаревший набор файлов диалога не стёрт"


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_current_message():
    """Fail-open: Redis лёг → работаем по текущему сообщению, а не падаем."""

    class _Boom:
        def get(self, key):
            raise ConnectionError("redis down")

        def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

        def delete(self, key):
            raise ConnectionError("redis down")

    out = await ac._recall_or_persist_thread_tabular(_Boom(), "t-1", ["fresh-1"], has_new_file=True)

    assert out == ["fresh-1"]


def test_call_site_actually_passes_the_dialog_files():
    """⚠️ Ограничение должно быть ПОДКЛЮЧЕНО, а не просто поддерживаться функцией.

    Тесты выше проверяют ``list_user_tabular_file_links`` отдельно и остаются зелёными,
    если из вызова в воркере убрать ``file_ids=`` — а это и есть возврат к прежнему
    поведению «весь аккаунт». Поэтому проверяем стык структурно (по AST, не текстом:
    аргумент легко «найти» в соседнем комментарии).
    """

    def _calls_to(func, name: str) -> list[ast.Call]:
        """Вызовы ``name(...)`` — и голым именем, и через модуль (``mod.name(...)``)."""
        tree = ast.parse(inspect.getsource(func))
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            if isinstance(called, ast.Name) and called.id == name:
                out.append(node)
            elif isinstance(called, ast.Attribute) and called.attr == name:
                out.append(node)
        return out

    # Ограничение действует там, где ходят в БД — в ОБОИХ списках (таблицы и песочница).
    for name in ("list_user_tabular_file_links", "list_user_dialog_file_links"):
        collected = _calls_to(ac.collect_thread_files, name)
        assert collected, f"сбор `{name}` исчез — половина файлов диалога пропадёт"
        for call in collected:
            assert any(kw.arg == "file_ids" for kw in call.keywords), (
                f"`{name}` собирает по всему аккаунту, без ограничения диалогом — "
                "давний .csv/.json снова начнёт выбрасывать текст вложений из промпта"
            )

    # ...и сам сбор подключён к потоку обработки сообщения.
    # ⚠️ Сбор переехал в `chat_worker/turn_context.py`; правило про `file_ids` то же.
    from service.services.chat.infrastructure.chat_worker import turn_context as tc

    assert _calls_to(tc.collect_engine_inputs, "collect_thread_files"), (
        "воркер не собирает файлы диалога — ни analyze_data, ни песочница их не увидят"
    )
