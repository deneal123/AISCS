"""Документ рядом с таблицей не пропадает, даже если клиент не назвал модальности.

Текст ТАБЛИЧНЫХ файлов из промпта убирается намеренно: он дублируется ссылкой, по которой
работает `analyze_data`. Но `file_context` — единый блоб, и вместе с табличным текстом
уходит текст СОСЕДНЕГО документа. Признак «рядом с таблицей есть документ» отменяет этот
сброс — и читался он ТОЛЬКО из `attachments[].kind`, которые проставляет наш фронт.

🔴 ЗАМЕРЕНО. Сообщение с двумя вложениями (`sales.csv` — факт, `plan.txt` — план) и
`file_ids` обоих, но без `attachments`:

    ОТВЕТ: «Для ответа мне необходимы данные о плановых продажах. Уточните, где находится
            информация о планах…»

Оба файла загружены и извлечены (80 и 176 символов), но план до модели не доехал. С
`attachments` тот же вопрос отвечается верно: «Казань, Омск».

Так ходит не только сторонний клиент: `file_ids` — самодостаточный способ приложить файл,
и наш собственный HTTP-путь уже однажды терял их молча. Backend знает имена файлов диалога
сам, поэтому признак больше не зависит от того, что прислал клиент.

⚠️ Запасной путь ГРУБЕЕ основного и не заменяет его: `attachments` несут модальность,
вычисленную по СОДЕРЖИМОМУ (`.json` бывает и таблицей, и деревом настроек), а здесь решает
расширение.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure import agent_context


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Референс-картинка и графы репо к этой проверке отношения не имеют."""

    async def _none(*a, **kw):
        return None

    async def _empty(*a, **kw):
        return []

    monkeypatch.setattr(agent_context, "recall_last_thread_image_url", _none)
    monkeypatch.setattr(agent_context, "read_thread_repo_graphs", _empty)


async def _has_document(attachments, dialog_files):
    _, has_document, _ = await agent_context.collect_message_extras(
        None, "t-1", attachments, dialog_files=dialog_files
    )
    return has_document


@pytest.mark.asyncio
async def test_the_document_is_seen_without_client_kinds():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: клиент не прислал модальности, но файлы
    диалога говорят сами за себя."""
    files = [{"name": "sales.csv"}, {"name": "plan.txt"}]

    assert await _has_document(None, files) is True


@pytest.mark.asyncio
async def test_client_kinds_still_win_when_present():
    """⚠️ Основной путь не тронут: модальность от клиента точнее расширения."""
    attachments = [{"kind": "document", "name": "спека"}]

    assert await _has_document(attachments, None) is True


@pytest.mark.asyncio
async def test_only_tables_means_no_document():
    """🔴 ГРАНИЦА, РАДИ КОТОРОЙ ВСЁ И ЗАДУМАНО. Приложены ОДНИ таблицы — их текст обязан
    уйти из промпта: он дублирует ссылку `analyze_data`, а лишние токены платит человек."""
    files = [{"name": "sales.csv"}, {"name": "prices.xlsx"}, {"name": "rows.json"}]

    # ⚠️ `attachments=None`: элемент без `kind` трактуется как документ (консервативно —
    # лишние токены дешевле ослепшего агента), и подмешать их сюда значило бы
    # проверять не то правило.
    assert await _has_document(None, files) is False


@pytest.mark.asyncio
async def test_an_archive_counts_as_a_document():
    """🔴 ЖИВОЙ ИНЦИДЕНТ, С КОТОРОГО ПРАВИЛО НАЧАЛОСЬ: `.json` + `.zip` и просьба
    отревьюить код — `.json` делал таблицы непустыми, карту репозитория выбрасывало, и
    агент отвечал «вставьте код»."""
    files = [{"name": "data.json"}, {"name": "src.zip"}]

    assert await _has_document(None, files) is True


@pytest.mark.asyncio
async def test_code_files_count_too():
    """⚠️ Код едет в промпт текстом — как документ, а не как таблица."""
    assert await _has_document(None, [{"name": "main.py"}]) is True


@pytest.mark.asyncio
async def test_no_files_at_all_is_not_a_document():
    """⚠️ Пусто — значит пусто: признак не должен становиться вечно истинным, иначе
    табличный текст перестанет отбрасываться вовсе и каждый ход подорожает."""
    assert await _has_document(None, None) is False
    assert await _has_document([], []) is False


@pytest.mark.asyncio
async def test_the_filename_may_arrive_under_either_key():
    """⚠️ Списки файлов в этом коде носят имя то в `name`, то в `filename` — читать надо
    оба, иначе признак молча выродится в «документов не бывает»."""
    assert await _has_document(None, [{"filename": "спека.pdf"}]) is True


def test_the_turn_passes_its_files_to_the_rule():
    """🔴 ТОЧКА ВЫЗОВА, И МУТАЦИЯ ПОКАЗАЛА, ЧТО ОНА НЕ СТЕРЕГЛАСЬ. Правило верно, но если
    ход не отдаёт ему файлы диалога — запасного пути нет, и документ снова пропадёт у
    любого клиента, который прислал одни `file_ids`.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import turn_context

    tree = ast.parse(inspect.getsource(turn_context.collect_engine_inputs).strip())
    passed = [
        kw
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "collect_message_extras"
        for kw in node.keywords
        if kw.arg == "dialog_files"
    ]

    assert passed, "ход не передаёт файлы диалога — запасной путь мёртв"
