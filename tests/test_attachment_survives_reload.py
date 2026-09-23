"""Вложение пользователя переживает перезагрузку страницы — на ВСЕХ путях записи хода.

🔴 ЖИВОЙ КАДР. Файл виден в сообщении до F5 и исчезает после. До перезагрузки он живёт
в стейте фронта, после — берётся из БД, а туда его клал только УСПЕШНЫЙ путь воркера.
Путей же четыре, и три писали реплику пользователя с пустой метой:

* короткое замыкание по кредитам (в том самом кадре было «Кредиты закончились»);
* аварийный персист частичного ответа (стрим оборвался после отданных токенов);
* фолбэк без воркера — там в INSERT не было колонки `metadata` вовсе.

⚠️ Тот же класс, что уже чинили для `mode_offer` и кольца контекста: свойство есть у
одного пути и молча отсутствует у соседнего, потому что оба пишут в одну таблицу.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from service.services.chat.domain.attachment_meta import user_message_meta

ATTACHED = [{"name": "А - рассылка.json", "kind": "document"}]
EXPECTED = {"attachments": [{"filename": "А - рассылка.json", "file_type": "document"}]}


def test_rule_itself_keeps_name_and_kind():
    assert user_message_meta(ATTACHED) == EXPECTED


# --- путь 1: короткое замыкание по кредитам -------------------------------------------


class _Pub:
    def __init__(self):
        self.payloads: list[dict] = []

    def publish_payload(self, payload):
        self.payloads.append(payload)
        return True


@pytest.mark.asyncio
async def test_no_credits_short_circuit_keeps_the_attachment(monkeypatch):
    """⚠️ ГЛАВНОЕ. Именно этот путь сработал в живом кадре («Кредиты закончились»)."""
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    captured: dict = {}

    async def _persist(**kw):
        captured.update(kw)
        return True

    async def _status(*a, **kw):
        return None

    monkeypatch.setattr(cwt, "_persist_chat_turn", _persist)
    monkeypatch.setattr(cwt, "_update_job_status_with_session", _status)

    await cwt._emit_insufficient_credits(
        publisher=_Pub(),
        job_repo=object(),
        session=object(),
        job_id="j1",
        thread_id="t1",
        text="вычитай 10 строку",
        user_id="u1",
        selected_model=None,
        reply="Кредиты закончились",
        attachments=ATTACHED,
    )

    assert captured.get("user_metadata") == EXPECTED, (
        "отказ по кредитам записал реплику без вложений — файл исчезнет при перезагрузке"
    )


# --- путь 2: аварийный персист частичного ответа --------------------------------------


@pytest.mark.asyncio
async def test_partial_turn_keeps_the_attachment(monkeypatch):
    import service.services.chat.infrastructure.chat_worker_tasks as cwt

    captured: dict = {}

    async def _persist(**kw):
        captured.update(kw)
        return True

    class _Session:
        async def commit(self):
            return None

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Pg:
        def get_session_context(self):
            return _Ctx()

    # ⚠️ ПАТЧИМ ТАМ, ГДЕ ЧИТАЮТ: запись хода переехала в `chat_worker/turn_result.py`
    # вместе с остальной фиксацией результата — подмена в старом модуле не влияет.
    from service.services.chat.infrastructure.chat_worker import turn_result

    monkeypatch.setattr(turn_result, "_persist_chat_turn", _persist)

    await cwt._persist_partial_turn_committed(
        _Pg(), "t1", "вопрос", "частичный ответ", "u1", user_message_meta(ATTACHED)
    )

    assert captured.get("user_metadata") == EXPECTED


# --- путь 3: фолбэк без воркера -------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_insert_writes_metadata_column():
    """🔴 В INSERT фолбэка колонки `metadata` не было вовсе — писать было некуда."""
    from service.services.chat.persistence.chat_repository import ChatRepository

    captured: dict = {}

    class _Session:
        async def execute(self, stmt, params=None):
            captured["sql"] = str(stmt)
            captured["params"] = params

        async def commit(self):
            return None

    class _Ctx:
        async def __aenter__(self):
            return _Session()

        async def __aexit__(self, *exc):
            return False

    class _Conn:
        def get_session_context(self):
            return _Ctx()

    repo = ChatRepository.__new__(ChatRepository)
    repo._get_connector = lambda: _Conn()  # type: ignore[method-assign]

    await repo.insert_message(
        thread_pk=1, sender="user", content="вопрос", metadata=user_message_meta(ATTACHED)
    )

    assert '"metadata"' in captured["sql"], "колонка метаданных не пишется вовсе"
    assert "А - рассылка.json" in captured["params"]["meta"]


def test_fallback_call_site_passes_the_attachments():
    """⚠️ ТОЧКА ВЫЗОВА. Возможности мало — ею надо воспользоваться."""
    import textwrap

    from service.services.chat.domain import chat_service as cs

    tree = ast.parse(textwrap.dedent(inspect.getsource(cs.ChatService.post_message)))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "persist_messages"
    ]
    assert calls, "фолбэк перестал сохранять ход вовсе"
    for call in calls:
        rendered = ast.dump(call)
        assert "user_message_meta" in rendered, (
            "фолбэк пишет реплику пользователя без вложений — файл исчезнет после F5"
        )


# --- путь 4: успешный прогон (был исправен, стережём от регресса) ---------------------


def test_success_path_still_passes_the_attachments():
    from service.services.chat.infrastructure.chat_worker import run_execution

    src = inspect.getsource(run_execution._finalize_success)
    assert "user_message_meta(request.attachments)" in src
    assert "user_metadata={} if confirmed_offer else" in src
