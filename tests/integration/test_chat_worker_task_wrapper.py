import service.services.chat.infrastructure.chat_worker_tasks as tasks
from service.services.chat.infrastructure.chat_worker_tasks import process_agent_message


def test_task_wrapper_delegates_to_async_impl(monkeypatch):
    """Celery-обёртка — это мост sync→async: она поднимает event loop и пробрасывает
    аргументы в process_agent_message_async.

    Раньше тест проверял делегирование в ``process_chat_message_handler``, но воркер
    отрефакторили: через хендлер ходит HTTP/WS-путь, а celery-задача выполняет работу
    сама (БД, биллинг, стриминг). Из-за этого тест уходил в реальную БД с фиктивным
    ``thread-1`` и падал на невалидном UUID. Проверяем то, за что обёртка отвечает на
    самом деле, — маппинг аргументов, без похода в базу.
    """
    captured = {}

    async def _fake_async(**kwargs):
        captured.update(kwargs)
        return {"status": "success", "reply": "ok", "metadata": {}}

    monkeypatch.setattr(tasks, "process_agent_message_async", _fake_async)

    result = process_agent_message.run(
        job_id="job-1",
        thread_id="thread-1",
        text="hello",
        user_id=1,
        session_data={"session_id": "thread-1"},
        selected_model=None,
        route_override=None,
        input_type=None,
        web_search=False,
        deep_research=False,
        file_context="",
    )

    assert result["status"] == "success"
    assert captured["job_id"] == "job-1"
    assert captured["thread_id"] == "thread-1"
    assert captured["text"] == "hello"
    # user_id приводится к строке: ниже по стеку он идёт в scoped-ключи памяти/биллинга.
    assert captured["user_id"] == "1"
    # None-file_context нормализуется в "", иначе сборка контекста получит None.
    assert captured["file_context"] == ""
    # id celery-задачи прокидывается: по нему воркер видит Redis-флаг отмены.
    assert "celery_task_id" in captured
