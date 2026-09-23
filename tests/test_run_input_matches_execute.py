"""Страж: тело ``/run`` не должно «уплыть» от сигнатуры ``execute``.

Живёт здесь, потому что требует ОБЕ стороны: контракт (``gpthub_core``) и сам движок
(``DefaultAgentExecutionService``). В backend движка больше нет, и там проверка стала бы
невозможной. Расхождение здесь не абстрактно: ``to_execute_kwargs`` развернёт лишнее поле
в аргумент, которого у ``execute`` нет, — и упадёт КАЖДЫЙ прогон в http-режиме.
"""

import inspect

from service.schemas.run import AMBIENT_FIELDS, AgentRunInput


def test_dto_fields_are_subset_of_execute_signature() -> None:
    """DTO не должен «уплыть» от порта: каждое поле = реальный параметр execute.

    Исключение — ``AMBIENT_FIELDS`` (окружение прогона): они в сигнатуру не входят ПО
    ЗАМЫСЛУ и отфильтрованы в ``to_execute_kwargs``.
    """
    from service.application.agent_execution_service import (
        DefaultAgentExecutionService,
    )

    params = set(inspect.signature(DefaultAgentExecutionService.execute).parameters) - {"self"}
    fields = set(AgentRunInput.model_fields) - AMBIENT_FIELDS
    extra = fields - params
    assert not extra, f"поля DTO вне сигнатуры execute (to_execute_kwargs сломает вызов): {extra}"
    # несериализуемый транспорт/сессия НЕ моделируются в теле запроса
    assert {"pseudo_session", "on_event"} & fields == set()
