"""HTTP-ручка сообщения не теряет поля, которые объявила в схеме.

🔴 НАЙДЕНО СКВОЗНЫМ ПРОГОНОМ ПУТЁМ ЧЕЛОВЕКА (регистрация → код из письма → вход → загрузка
файла → вопрос). Файл `.py` загружен успешно, `file_ids` передан в
`POST /api/chats/{id}/message` — агент ответил «пришлите код функции add».

Причина: `MessageRequest` объявляет `file_ids` и `watch_video`, а use-case их НЕ ПЕРЕДАВАЛ.
WS-путь возит те же поля своим каналом (`session_data`), поэтому в интерфейсе всё работало,
а HTTP-ручка молча обещала то, чего не делала.

Цена не в одном поле: из `file_ids` выводится признак «в этом сообщении новый файл», а от
него зависят импорт в песочницу, восстановление текста вложения и память треда о файлах.
Пустой признак гасил всю цепочку разом.

⚠️ `watch_video` — согласие на ДОРОГОЕ (просмотр ролика). По HTTP его нельзя было включить
вовсе, то есть способность существовала только в одном из двух путей.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.services.chat.domain.chat_contracts import ChatRequestContext


class _Chat:
    """Двойник сервиса: запоминает контекст, который ему передали."""

    def __init__(self):
        self.seen: ChatRequestContext | None = None

    async def post_message(self, context):
        self.seen = context
        return SimpleNamespace(reply="ok", thread_id="t-1", metadata=SimpleNamespace(data={}))


def _payload(**over):
    base = {
        "text": "что в файле?",
        "user_id": "u-1",
        "model": None,
        "route_override": None,
        "input_type": None,
        "web_search": False,
        "deep_research": False,
        "file_context": "",
        "file_ids": [],
        "watch_video": False,
        "attachments": [],
    }
    base.update(over)
    return SimpleNamespace(**base)


async def _run(payload):
    from service.services.chat.application.use_cases.chat_use_cases import PostMessageUseCase

    chat = _Chat()
    await PostMessageUseCase(chat).execute(thread_id="t-1", payload=payload)
    assert chat.seen is not None, "use-case не позвал сервис вовсе"
    return chat.seen


# --- поля доезжают ------------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_file_ids_reach_the_service():
    """🔴 ГЛАВНОЕ. Из них выводится «новый файл в этом сообщении» — без них не работают ни
    песочница, ни восстановление текста, ни память треда."""
    seen = await _run(_payload(file_ids=["f-1", "f-2"]))

    assert seen.file_ids == ["f-1", "f-2"], "file_ids потеряны — файл до агента не доедет"


@pytest.mark.asyncio
async def test_watch_video_consent_reaches_the_service():
    """🔴 Согласие на ДОРОГОЕ. По HTTP его нельзя было включить вовсе."""
    seen = await _run(_payload(watch_video=True))

    assert seen.watch_video is True, "согласие на просмотр видео потеряно"


@pytest.mark.asyncio
async def test_empty_values_stay_empty():
    """🔴 ГРАНИЦА. Пусто обязано остаться пустым: `file_ids=[]` — это «файлов нет», а не
    «поле не пришло», и подставлять сюда что-либо значит воскрешать чужое вложение."""
    seen = await _run(_payload())

    assert seen.file_ids is None
    assert seen.watch_video is False


@pytest.mark.asyncio
async def test_previously_carried_fields_still_arrive():
    """⚠️ Правка добавляет поля, а не перекраивает передачу: остальное обязано доезжать
    как прежде."""
    seen = await _run(
        _payload(
            text="привет",
            file_context="текст документа",
            attachments=[{"kind": "document", "filename": "a.pdf"}],
            web_search=True,
            deep_research=True,
            model="openai/gpt-4o",
        )
    )

    assert seen.text == "привет"
    assert seen.file_context == "текст документа"
    assert seen.attachments and seen.attachments[0]["filename"] == "a.pdf"
    assert seen.web_search is True and seen.deep_research is True
    assert seen.selected_model == "openai/gpt-4o"


# --- дальше по цепочке -------------------------------------------------------------------- #


def test_the_contract_carries_both_fields():
    """⚠️ Контракт — общее звено обоих путей. Не будь в нём полей, use-case не смог бы их
    передать даже при желании."""
    fields = ChatRequestContext.__dataclass_fields__

    assert "file_ids" in fields and "watch_video" in fields


def test_every_orchestrator_call_passes_both_fields():
    """🔴 ЗВЕНО, КОТОРОЕ Я СНАЧАЛА НЕ ЗАКРЫЛ. Мутация «сервис не передаёт поля оркестратору»
    прошла ЗЕЛЁНОЙ: тесты стерегли вход цепочки (use-case) и выход (session_data), а
    середину — нет. Цепочка из четырёх звеньев обрывается в любом.

    ⚠️ ВЫЗОВОВ ДВА (обычный путь и путь с ожиданием), и проверяются ОБА: починить один и
    забыть второй — самый естественный способ оставить поломку половине пользователей.
    """
    import ast
    import inspect

    from service.services.chat.domain import chat_service as cs

    tree = ast.parse(inspect.getsource(cs).strip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and any(kw.arg == "file_context" for kw in node.keywords)
    ]

    assert len(calls) >= 2, f"вызовов оркестратора найдено {len(calls)} — тест устарел"
    for call in calls:
        names = {kw.arg for kw in call.keywords}
        assert {"file_ids", "watch_video"} <= names, (
            f"вызов оркестратора теряет поля: не хватает {{'file_ids','watch_video'}} - {names}"
        )


def test_the_orchestrator_puts_them_into_session_data():
    """🔴 ТОЧКА ВЫЗОВА. Воркер читает оба поля ИЗ `session_data` — тем же каналом, что у WS.
    Не положи их туда, поля дошли бы до оркестратора и умерли в нём.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена.
    """
    import ast
    import inspect

    from service.services.chat.domain import chat_job_orchestrator as orch

    tree = ast.parse(inspect.getsource(orch.ChatJobOrchestrator.execute).strip())
    written = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }

    assert {"file_ids", "watch_video"} <= written, (
        "оркестратор не кладёт поля в session_data — воркер их не увидит"
    )
