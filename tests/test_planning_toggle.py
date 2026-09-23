"""Планирование управляемо пользователем, а не только «включается само».

Стратегия `plan` существовала и работала, но включалась ИСКЛЮЧИТЕЛЬНО по внутренней
оценке сложности — снаружи её нельзя было ни попросить, ни отключить. Три состояния:

* `None`  — как раньше: план строится, если `assess_is_complex` сочла запрос сложным;
* `True`  — строится ВСЕГДА, и оценка при этом НЕ ЗАПРАШИВАЕТСЯ (это отдельный вызов
  модели: спрашивать «сложно ли», когда человек уже сказал «планируй», — платить зря);
* `False` — не строится никогда.

⚠️ Проверяем ПОВЕДЕНИЕМ, а не чтением исходника: считаем, сколько раз позваны оценка и
построение плана. Флаг, доехавший до сигнатуры и не прочитанный условием, неотличим от
отсутствующего — интерфейс показывает переключатель, а поведение прежнее.
"""

from __future__ import annotations

import pytest

from service.application import processor_steps as steps
from service.domain.run_context import RunExecutionContext


@pytest.fixture()
def spy(monkeypatch):
    """Считает вызовы оценки сложности и построения плана."""
    calls = {"assess": 0, "plan": 0}

    async def _assess(*_a, **_kw):
        calls["assess"] += 1
        # «Сложно» — чтобы авто-ветка САМА построила план: так видно разницу между
        # «не строили, потому что запретили» и «не строили, потому что не сложно».
        return True

    async def _plan(*_a, **_kw):
        calls["plan"] += 1
        return "ПЛАН", []

    # ⚠️ ПАТЧИМ ТАМ, ГДЕ ЧИТАЮТ. Гейт переехал из `processor_steps` в `planning`
    # (`resolve_plan`), и патч по старому адресу перестал бы существовать вовсе —
    # AttributeError. Останься имя на прежнем месте, подмена молча ничего бы не делала,
    # а тесты остались бы зелёными, не проверив ничего.
    from service.domain.pipeline import planning as planning_mod

    monkeypatch.setattr(planning_mod, "assess_is_complex", _assess)
    monkeypatch.setattr(planning_mod, "build_plan", _plan)
    return calls


class _Orchestrator:
    """Возвращает маршрут без сети: гейт планирования проверяем, а не роутинг."""

    async def route(self, *_a, **kw):
        return kw.get("route_override") or "general"


class _Step(steps.ProcessorStepsMixin):
    """Минимальный хозяин миксина — см. требования в докстринге модуля шагов."""

    model_id = "m"
    orchestrator = _Orchestrator()


async def _plan_context(planning):
    decision, _events = await _Step()._resolve_route_and_plan(
        user_input="сравни три подхода и предложи план внедрения",
        thread_id="t",
        route_override=None,
        resolved_category="general",
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=False,
        planning=planning,
        file_context=None,
        attachments=None,
        execution=RunExecutionContext(),
    )
    return decision.plan_context


@pytest.mark.asyncio
async def test_auto_keeps_todays_behaviour(spy):
    """`None` — как раньше: спрашиваем оценку и строим план, если она сказала «сложно»."""
    assert await _plan_context(None) == "ПЛАН"
    assert spy == {"assess": 1, "plan": 1}


@pytest.mark.asyncio
async def test_explicit_yes_skips_the_assessment(spy):
    """🔴 Явное «да» строит план И НЕ ТРАТИТ вызов на оценку сложности."""
    assert await _plan_context(True) == "ПЛАН"
    assert spy["plan"] == 1
    assert spy["assess"] == 0, "оценка запрошена впустую — человек уже сказал «планируй»"


@pytest.mark.asyncio
async def test_explicit_no_disables_planning_entirely(spy):
    """Явное «нет» не строит план и тоже не тратит вызов на оценку."""
    assert await _plan_context(False) is None
    assert spy == {"assess": 0, "plan": 0}


@pytest.mark.asyncio
async def test_forced_mode_still_wins(spy):
    """Форс-режим по-прежнему отменяет планирование: маршрут задан, стратегия ни при чём."""
    decision, _ = await _Step()._resolve_route_and_plan(
        user_input="сравни три подхода",
        thread_id="t",
        route_override="web_search",
        resolved_category=None,
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=False,
        planning=True,
        file_context=None,
        attachments=None,
        execution=RunExecutionContext(),
    )
    assert decision.plan_context is None
    assert spy == {"assess": 0, "plan": 0}


def test_planning_is_part_of_the_contract():
    """Поле обязано быть в теле /run: иначе выбор пользователя не доедет до сайдкара."""
    from service.schemas.run import AgentRunInput

    assert "planning" in AgentRunInput.model_fields
    assert AgentRunInput(text="q", thread_id="t").planning is None, (
        "умолчание должно быть «авто», а не выключено"
    )


def test_flag_reaches_execute():
    """ТОЧКА ВЫЗОВА: поле контракта обязано быть аргументом `execute` и уехать дальше."""
    import inspect

    from service.application.agent_execution_service import DefaultAgentExecutionService

    assert "planning" in inspect.signature(DefaultAgentExecutionService.execute).parameters
    assert "planning=planning" in inspect.getsource(DefaultAgentExecutionService.execute)


# --------------------------------------------------------------------------- #
# План видно, а не только «план готов»                                          #
# --------------------------------------------------------------------------- #
def _resp(content: str):
    """Ответ провайдера ОБЪЕКТОМ, а не словарём.

    ⚠️ `first_message_content` читает всё через `getattr` (провайдеров пять, и не у всех
    это pydantic-модель OpenAI). Словарь она разбирает в ПУСТУЮ СТРОКУ — фейк из dict
    молча подменял бы проверяемый случай на «модель промолчала», и оба теста ниже падали
    бы, указывая не на ту причину.
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None
    )


@pytest.mark.asyncio
async def test_plan_text_is_emitted_to_the_trace(monkeypatch):
    """🔴 ЖИВАЯ ЖАЛОБА: режим включён, а увидеть план негде.

    Наружу уезжало ОДНО ЧИСЛО — «План готов: 7 шаг(ов)». План при этом строился,
    подмешивался в промпт и влиял на ответ. Человек включил «Планирование» и не мог
    узнать ни что запланировано, ни выполнилось ли это: тумблер, чьё действие
    ненаблюдаемо, неотличим от выключенного.
    """
    from service.domain.pipeline import planning

    async def _models():
        return ["openai/gpt-4o-mini"]

    async def _completion(**_kw):
        return _resp("1. Прочитать файл\n2. Свести выводы")

    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)
    monkeypatch.setattr("service.domain.client.create_chat_completion", _completion)

    plan, events = await planning.build_plan("сложная задача", model="openai/gpt-4o-mini")

    assert plan.startswith("1. Прочитать файл")
    done = [e for e in events if e.metadata and "plan" in (e.metadata or {})]
    assert done, "текст плана никуда не уехал — в трейсе снова будет только число шагов"
    assert "Прочитать файл" in done[0].metadata["plan"]
    assert done[0].metadata["steps"] == 2


@pytest.mark.asyncio
async def test_plan_metadata_is_capped(monkeypatch):
    """План — вывод модели, а не наш текст: неограниченная строка в событие не едет."""
    from service.domain.pipeline import planning

    async def _models():
        return ["openai/gpt-4o-mini"]

    async def _completion(**_kw):
        return _resp("1. шаг\n" * 5000)

    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)
    monkeypatch.setattr("service.domain.client.create_chat_completion", _completion)

    _plan, events = await planning.build_plan("задача", model="openai/gpt-4o-mini")

    payload = [e for e in events if e.metadata and "plan" in (e.metadata or {})][0]
    assert len(payload.metadata["plan"]) <= 4000


# --------------------------------------------------------------------------- #
# Отказ объясняется, а не проходит молча                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_refusal_is_explained_when_planning_was_requested(spy):
    """🔴 Явное «планируй» + непригодный маршрут → в трейсе ПРИЧИНА, а не тишина.

    Живая жалоба: «принудительно включил планирование, в трейсах не увидел ничего».
    Снаружи «флаг не доехал», «гейт отказал» и «план построен, но не показан» выглядели
    ОДИНАКОВО — разобрать было нечем, а молчание на явную просьбу читается как «тумблер
    не работает».
    """
    _decision, events = await _Step()._resolve_route_and_plan(
        user_input="сравни подходы",
        thread_id="t",
        route_override="web_search",
        resolved_category=None,
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=False,
        planning=True,
        file_context=None,
        attachments=None,
        execution=RunExecutionContext(),
    )

    skipped = [e for e in events if (e.metadata or {}).get("kind") == "plan_skipped"]
    assert skipped, "отказ по явной просьбе прошёл молча"
    assert "web_search" in skipped[0].data, "причина не названа — объяснять нечем"


@pytest.mark.asyncio
async def test_auto_mode_stays_quiet_about_skipping(monkeypatch, spy):
    """А вот АВТО молчит: «не сложно» — штатное решение, а не отказ на просьбу."""

    async def _not_complex(*_a, **_kw):
        return False

    from service.domain.pipeline import planning as planning_mod

    monkeypatch.setattr(planning_mod, "assess_is_complex", _not_complex)

    _decision, events = await _Step()._resolve_route_and_plan(
        user_input="привет",
        thread_id="t",
        route_override=None,
        resolved_category="general",
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=False,
        planning=None,
        file_context=None,
        attachments=None,
        execution=RunExecutionContext(),
    )

    assert not [e for e in events if (e.metadata or {}).get("kind") == "plan_skipped"]
