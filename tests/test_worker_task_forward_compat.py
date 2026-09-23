"""Задача воркера обязана переживать РАССИНХРОН ВЕРСИЙ с backend'ом.

🔴 Живой инцидент: добавление поля `persona_ids` в вызов задачи уронило КАЖДЫЙ чат, пока
воркер не перезапустили. Celery валит задачу с неизвестным kwarg ДО тела — то есть мимо
`_handle_job_failure`: резерв не освобождается, ошибка не публикуется, пользователь видит
вечный спиннер вместо сообщения о сбое.

Окно рассинхрона неизбежно при любом выкате, где backend обновляется раньше воркеров.
"""

from __future__ import annotations

import logging

import pytest

import service.services.chat.infrastructure.chat_worker_tasks as cwt


@pytest.fixture()
def capture_worker_logs(caplog):
    """Перехват записей воркера НЕЗАВИСИМО от порядка тестов.

    ⚠️ Без этого тест зелёный в одиночку и красный в наборе: `LOGGING` в
    `service/settings.py` объявляет логгер `service` с `propagate: False`, а
    `service/main.py` применяет dictConfig на импорте. Стоит соседнему тесту
    импортировать `main` раньше — и записи перестают доходить до корневого перехватчика
    pytest. Тот же приём уже применён в `test_charge_usage_anomaly.py`.
    """
    worker_logger = logging.getLogger(cwt.__name__)
    worker_logger.addHandler(caplog.handler)
    previous = worker_logger.level
    worker_logger.setLevel(logging.WARNING)
    try:
        yield caplog
    finally:
        worker_logger.removeHandler(caplog.handler)
        worker_logger.setLevel(previous)


def _run(**kwargs):
    """Позвать тело celery-задачи напрямую, минуя брокер."""
    fn = getattr(cwt.process_agent_message, "run", cwt.process_agent_message)
    return fn(job_id="j", thread_id="t", text="привет", user_id=None, **kwargs)


def test_unknown_kwarg_does_not_kill_the_task(monkeypatch, capture_worker_logs):
    """Неизвестное поле ПРОИГНОРИРОВАНО, задача отработала, в логах — предупреждение."""
    seen: dict = {}

    async def _fake_async(**kw):
        seen.update(kw)
        return {"reply": "ок"}

    monkeypatch.setattr(cwt, "process_agent_message_async", _fake_async)

    with capture_worker_logs.at_level(logging.WARNING):
        result = _run(persona_ids=["analyst"], полеИзБудущего="значение")

    assert result == {"reply": "ок"}, "задача упала на поле из будущего"
    assert "персона" not in str(seen), "неизвестное поле просочилось в пайплайн"
    assert seen.get("persona_ids") == ["analyst"], "известное поле потерялось"

    warnings = [
        r.getMessage() for r in capture_worker_logs.records if "воркер старее" in r.getMessage()
    ]
    assert warnings, "деградация прошла МОЛЧА — рассинхрон версий останется незамеченным"
    assert "полеИзБудущего" not in warnings[0], "имя неизвестного wire-поля попало в лог"
    records = [
        record for record in capture_worker_logs.records if "воркер старее" in record.getMessage()
    ]
    assert records[0].unknown_field_count == 1


def test_known_kwargs_are_not_swallowed(monkeypatch):
    """Обратная сторона: объявленные поля обязаны доезжать, а не попадать в catch-all."""
    seen: dict = {}

    async def _fake_async(**kw):
        seen.update(kw)
        return {}

    monkeypatch.setattr(cwt, "process_agent_message_async", _fake_async)

    _run(multi_intent=True, ldr_strategy="langgraph-agent", persona_ids=["tarot"])

    assert seen["multi_intent"] is True
    assert seen["ldr_strategy"] == "langgraph-agent"
    assert seen["persona_ids"] == ["tarot"]
