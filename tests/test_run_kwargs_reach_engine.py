"""Каждое поле тела `/run` доезжает до движка, не спотыкаясь о промежуточный слой.

⚠️ НАЙДЕНО ЖИВЫМ ЗАПУСКОМ. Первый же реальный запрос к поднятому сайдкару вернул
`TypeError: PrepareExecutionContextUseCase.execute() got an unexpected keyword argument
'resolved_category'`. Поле было добавлено в DTO и в сигнатуру сервиса, но не в
промежуточный use case — а `to_execute_kwargs()` кладёт в kwargs ВСЕ поля тела, включая
пустые. То есть ломался КАЖДЫЙ запрос `/run`, а не только те, где поле заполнено.

## Почему 1045 тестов молчали

Они зовут `AgentProcessor` напрямую или подменяют его целиком. Цепочку
`AgentRunInput → to_execute_kwargs → DefaultAgentExecutionService.execute →
PrepareExecutionContextUseCase` не проходил ни один: между DTO и движком три слоя, и
каждый принимает аргументы ПОИМЁННО, кроме последнего (`**kwargs`).

Отсюда форма стража: он сверяет ФАКТИЧЕСКИЕ поля DTO с тем, что готова принять
сигнатура сервиса, — то есть проверяет стык, а не поведение каждого поля.
"""

from __future__ import annotations

import inspect

import pytest

from service.application.agent_execution_service import DefaultAgentExecutionService
from service.schemas.run import AMBIENT_FIELDS, AgentRunInput


def _service_params() -> set[str]:
    sig = inspect.signature(DefaultAgentExecutionService.execute)
    return {
        name
        for name, p in sig.parameters.items()
        if p.kind is not inspect.Parameter.VAR_KEYWORD and name != "self"
    }


def test_service_accepts_every_field_of_the_run_body():
    """⚠️ ГЛАВНОЕ: то, что кладёт `to_execute_kwargs`, движок обязан принять.

    Поля тела уходят в kwargs ЦЕЛИКОМ, включая незаполненные. Значит несовпадение
    ломает не «редкий случай с новым полем», а любой запрос вообще.
    """
    body_fields = set(AgentRunInput.model_fields) - set(AMBIENT_FIELDS)
    accepted = _service_params()

    missing = sorted(body_fields - accepted)
    assert not missing, (
        f"поля тела /run не принимаются DefaultAgentExecutionService.execute: {missing}. "
        "to_execute_kwargs кладёт их в kwargs всегда — сломается КАЖДЫЙ запрос."
    )


def test_prepare_context_accepts_what_the_service_hands_it():
    """Промежуточный слой — ровно то место, где поле потерялось.

    Сервис зовёт `PrepareExecutionContextUseCase.execute` ПОИМЁННО, поэтому добавленный
    в сервис аргумент не доедет сам собой: use case обязан его знать.
    """
    from service.application.use_cases.agent_execution_use_cases import (
        PrepareExecutionContextUseCase,
    )

    src = inspect.getsource(DefaultAgentExecutionService.execute)
    passed = set()
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith("resolved_category=") or stripped.startswith("route_override="):
            passed.add(stripped.split("=", 1)[0])

    accepted = set(inspect.signature(PrepareExecutionContextUseCase.execute).parameters)
    missing = sorted(passed - accepted)
    assert not missing, f"use case не принимает переданное сервисом: {missing}"


@pytest.mark.asyncio
async def test_run_body_reaches_the_processor_end_to_end(monkeypatch):
    """Сквозной прогон DTO → сервис → процессор, с подменой только САМОГО процессора.

    Всё, что между ними, работает настоящее — иначе стык снова окажется непроверенным.
    """
    seen: dict = {}

    class _FakeProcessor:
        def __init__(self, *a, **kw):
            pass

        async def process_message_stream(self, **kwargs):
            seen.update(kwargs)
            return
            yield  # pragma: no cover

    import service.application.agent_execution_service as svc

    monkeypatch.setattr(svc, "AgentProcessor", _FakeProcessor)

    payload = AgentRunInput(
        text="сделай презентацию",
        thread_id="t1",
        route_override="pptx_gen",
        session_data={"_resolved_category": "general"},
    )
    await DefaultAgentExecutionService().execute(**payload.to_execute_kwargs(), on_event=None)

    assert seen, "процессор не был вызван — предпосылка теста неверна"
    assert seen.get("route_override") == "pdf_gen"
    assert seen.get("resolved_category") == "general", (
        "категория из бокового канала не доехала до процессора"
    )
