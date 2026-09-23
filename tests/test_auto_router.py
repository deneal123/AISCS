"""Вызов оркестратора: короткий путь бесплатен, сбой прозрачен.

Оркестратор — единственный служебный вызов на авто-пути, поэтому его цена и его отказ
проверяются поведением: сколько раз позвали модель и что осталось после сбоя.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain.routing import auto_router
from service.domain.routing.auto_decision import SOURCE_LLM, SOURCE_SHORTCUT


def _resp(content: str):
    """Ответ провайдера ОБЪЕКТОМ: `first_message_content` читает через `getattr`,
    словарь она разбирает в пустую строку и подменила бы проверяемый случай."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None
    )


@pytest.fixture()
def llm(monkeypatch):
    """Считает вызовы модели и отдаёт заданный ответ."""
    state = {"calls": 0, "content": '{"route":"web_search","confidence":"high"}', "boom": False}

    async def _models():
        # Strict admission must contain the explicitly requested model. Returning a
        # different model would correctly suppress the call instead of substituting it.
        return ["m"]

    async def _completion(**_kw):
        state["calls"] += 1
        if state["boom"]:
            raise RuntimeError("провайдер лёг")
        return _resp(state["content"])

    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)
    monkeypatch.setattr("service.domain.client.create_chat_completion", _completion)
    return state


@pytest.mark.asyncio
async def test_shortcut_costs_nothing(llm):
    """🔴 «Привет» не должен стоить вызова модели — это самый частый класс сообщений."""
    decision = await auto_router.decide_modes("привет", prompt_input="…", model="m")

    assert llm["calls"] == 0, "за приветствие заплатили вызовом модели"
    assert decision.source == SOURCE_SHORTCUT and decision.route == "general"


@pytest.mark.asyncio
async def test_content_message_asks_the_model(llm):
    from service.domain.run_context import RunExecutionContext

    decision = await auto_router.decide_modes(
        "а теперь найди свежее",
        prompt_input="контекст",
        model="m",
        execution=RunExecutionContext(),
    )

    assert llm["calls"] == 1
    assert decision.route == "web_search" and decision.source == SOURCE_LLM


@pytest.mark.asyncio
async def test_provider_failure_is_transparent(llm):
    """🔴 Сбой → `None` → поведение ровно прежнее: старый роутер И ЕСТЬ фолбэк нового."""
    from service.domain.run_context import RunExecutionContext

    llm["boom"] = True

    assert (
        await auto_router.decide_modes(
            "сравни подходы", prompt_input="к", model="m", execution=RunExecutionContext()
        )
        is None
    )


@pytest.mark.asyncio
async def test_unparseable_answer_is_transparent(llm):
    from service.domain.run_context import RunExecutionContext

    llm["content"] = "конечно! вот решение:"

    assert (
        await auto_router.decide_modes(
            "сравни подходы", prompt_input="к", model="m", execution=RunExecutionContext()
        )
        is None
    )


@pytest.mark.asyncio
async def test_fenced_json_is_accepted(llm):
    """Модели заворачивают ответ в ```-ограду вопреки прямому запрету в промпте."""
    llm["content"] = '```json\n{"route":"general","needs_plan":true}\n```'

    from service.domain.run_context import RunExecutionContext

    decision = await auto_router.decide_modes(
        "сравни подходы", prompt_input="к", model="m", execution=RunExecutionContext()
    )

    assert decision.route == "general" and decision.needs_plan is True


@pytest.mark.asyncio
async def test_usage_is_accumulated(llm):
    """Служебный вызов обязан попасть в счёт: иначе решение бесплатно для нас, но не для
    платформы."""
    from service.domain.run_context import RunExecutionContext

    execution = RunExecutionContext()
    llm["content"] = '{"route":"general"}'

    async def _completion(**_kw):
        llm["calls"] += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=llm["content"]))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=20, total_tokens=140),
        )

    import service.domain.client as client_mod

    client_mod.create_chat_completion = _completion
    await auto_router.decide_modes(
        "сравни подходы", prompt_input="к", model="m", execution=execution
    )

    assert execution.usage.prompt_tokens == 120
    assert execution.usage.completion_tokens == 20
