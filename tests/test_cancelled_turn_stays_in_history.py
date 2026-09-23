"""Нажал «стоп» — вопрос остаётся в истории. Раньше исчезал весь ход.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Новый пользователь, вопрос «напиши эссе на 2000 слов», через 8 с
отмена ручкой `POST /api/jobs/v1/task/{id}/cancel` (именно так жмёт «стоп» фронт):

    отмена: HTTP 200 {"cancelled": true}
    списано: 0 кредитов          ← деньги в порядке, резерв отпущен
    сообщений в треде: 2 → 2     ← ход НЕ СОХРАНИЛСЯ ВОВСЕ

Ни ответа, ни собственного вопроса: после перезагрузки страницы человек видит тред таким,
будто он ничего не спрашивал, и длинный вопрос надо набирать заново.

Причина — правило «сохранять, если успели уйти токены»: за 8 с не пришло ни одного `chunk`
(в событиях только `heartbeat`, `job_created`, `processing`). И это НЕ редкий случай, а
типичный для дорогих путей — файлы, deep research, поиск в сети: там до первого токена
уходят десятки секунд, и это ровно то время, когда жмут «стоп».

⚠️ ОТМЕНА И СБОЙ РАЗВЕДЕНЫ НАМЕРЕННО. Отмена намеренна, и пустой ход человек узнаёт как
свой. Системный сбой — нет: там ход без ответа выглядел бы мусором, и прежнее правило
(«только с токенами») оставлено дословно.
"""

from __future__ import annotations

import pytest

from service.services.chat.infrastructure.chat_worker.turn_result import (
    CANCELLED_NOTE,
    interrupted_reply_text,
)


def test_cancellation_without_a_single_token_still_writes_the_turn():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: отмена до первого чанка."""
    assert interrupted_reply_text([], cancelled=True) == CANCELLED_NOTE
    assert interrupted_reply_text(None, cancelled=True) == CANCELLED_NOTE


def test_a_partial_answer_survives_the_cancellation():
    """⚠️ Токены человек уже видел на экране — они обязаны остаться и в истории."""
    text = interrupted_reply_text(["Вычислительная ", "техника "], cancelled=True)

    assert text.startswith("Вычислительная техника")
    assert CANCELLED_NOTE in text, "пометка об остановке потеряна — ход выглядит законченным"


def test_a_system_failure_without_tokens_writes_nothing():
    """🔴 ГРАНИЦА, ОТДЕЛЯЮЩАЯ ОТМЕНУ ОТ СБОЯ. Расширь правило на все сбои — и тред заполнят
    вопросы без ответов, которых человек не просил."""
    assert interrupted_reply_text([], cancelled=False) == ""
    assert interrupted_reply_text(["   ", "\n"], cancelled=False) == ""


def test_a_system_failure_with_tokens_keeps_the_old_wording():
    """⚠️ Прежний путь не тронут: оборванный сбоем стрим помечается как прерванный, а не
    как остановленный человеком — иначе сбой выдавался бы за действие пользователя."""
    text = interrupted_reply_text(["часть ответа"], cancelled=False)

    assert "прервана" in text
    assert CANCELLED_NOTE not in text


def test_whitespace_only_stream_is_not_mistaken_for_an_answer():
    """⚠️ Пробелы — не ответ: иначе в истории окажется пустой пузырь вместо пометки."""
    assert interrupted_reply_text([" ", "\n\n"], cancelled=True) == CANCELLED_NOTE


@pytest.mark.parametrize("cancelled", [True, False])
def test_the_worker_asks_this_function_instead_of_deciding_itself(cancelled):
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а воркер решает сам — и они разойдутся. Мутации уже
    ловили ровно это в соседних узлах: тест держал функцию, а поломка жила в месте вызова.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена.
    """
    import ast
    import inspect

    from service.services.chat.infrastructure.chat_worker import failure

    tree = ast.parse(inspect.getsource(failure.handle_worker_failure).strip())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "interrupted_reply_text"
    ]

    assert calls, "воркер не зовёт правило — отменённый ход снова пропадёт из истории"
    # ⚠️ И признак отмены ДЕЙСТВИТЕЛЬНО выводится из исключения: передай туда `False` —
    # функция останется верной, а поведение вернётся к прежнему.
    kwargs = {kw.arg for call in calls for kw in call.keywords}
    assert "cancelled" in kwargs, "признак отмены не передан — правило выродится в прежнее"
    source = inspect.getsource(failure.handle_worker_failure)
    assert "CancelledByUser" in source, "отмену не отличают от сбоя"
