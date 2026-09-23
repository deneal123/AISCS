"""Пустой ответ модели доезжает до человека ОТКАЗОМ, а не молчанием.

🔴 ЖИВОЙ КАДР. Провал провайдера (403 «ключ исчерпан») приходил в воркер пустой строкой.
Воркер публиковал `agent_reply` без текста; фронт на пустой ответ гасит спиннер и не
рисует НИЧЕГО — ни сообщения, ни ошибки. Снаружи это неотличимо от «запрос потерялся».

⚠️ Тот же класс, что и с вложениями: HTTP-путь подменял пустой ответ честным отказом
(`chat_service.post_message` → `build_provider_unavailable_reply`) давно, а путь воркера
— нет. Оба заканчиваются `agent_reply`, и разница была невидима.
"""

from __future__ import annotations

import inspect

from service.services.chat.infrastructure.chat_worker_tasks import _reply_or_provider_failure


def test_empty_reply_becomes_an_honest_refusal():
    """⚠️ ГЛАВНОЕ. Пустая строка → текст отказа + признак недоступности провайдера."""
    reply, meta = _reply_or_provider_failure(
        {"reply": "   ", "metadata": {"provider_error": "403 Key limit exceeded"}}
    )

    assert reply.strip(), "пустой ответ уехал пользователю как есть — он увидит молчание"
    assert "403 Key limit exceeded" in reply, "причина отказа потеряна"
    assert meta["provider_unavailable"] is True, (
        "фронт не узнает, что ответа не было — трейс закроется как успешный"
    )
    assert meta["execution_status"] == "failed"


def test_real_reply_passes_through_untouched():
    reply, meta = _reply_or_provider_failure({"reply": "Готово", "metadata": {"usage": {"t": 1}}})

    assert reply == "Готово"
    assert "provider_unavailable" not in meta
    assert meta["usage"] == {"t": 1}
    assert meta["execution_status"] == "completed"


def test_legacy_partial_result_gets_a_terminal_status():
    _, meta = _reply_or_provider_failure(
        {"reply": "Есть часть результата", "metadata": {"deadline_exceeded": True}}
    )

    assert meta["execution_status"] == "timed_out"


def test_missing_metadata_does_not_explode():
    reply, meta = _reply_or_provider_failure({"reply": "", "metadata": None})

    assert reply.strip()
    assert meta["provider_unavailable"] is True


def test_wired_into_the_worker():
    """⚠️ ТОЧКА ВЫЗОВА: подмена должна стоять НА ПУТИ ответа, а не рядом с ним."""
    from service.services.chat.infrastructure.chat_worker import run_execution

    src = inspect.getsource(run_execution._finalize_success)
    assert "hooks.reply_or_provider_failure(execution_result)" in src, (
        "воркер снова публикует ответ модели напрямую — пустой уедет молчанием"
    )
    assert 'reply = str(execution_result["reply"])' not in src
