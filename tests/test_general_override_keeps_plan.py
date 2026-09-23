"""Форс `general` — не выбор человека, и глушить стратегии он не должен.

🔴 ЖИВАЯ ЖАЛОБА: «принудительно включил планирование, приложил PDF, в трейсах не увидел
ничего». Флаг доезжал; отказывал гейт. Причина: при вложении документа с извлечённым
текстом ФРОНТ сам ставит `route_override='general'` — чтобы категорийный роутер по словам
«сводка/тренды/выводы» не увёл запрос в веб-поиск мимо самого файла. А любой непустой
`route_override` выключал и планирование, и декомпозицию.

Итог был такой: ЛЮБОЕ сообщение с приложенным документом гарантированно теряло обе
стратегии, а человек читал «выбран режим «general», а не Авто» — про режим, которого он
не выбирал.

⚠️ Пункт «Обычный» в меню приходит сюда же, и это правильно: он обещает ответ БЕЗ
ИНСТРУМЕНТОВ, а не без плана. План инструментом не является — он подмешивается в тот же
единственный вызов модели.
"""

from __future__ import annotations

import pytest

from service.application import processor_steps as steps
from service.domain.pipeline.planning import plan_blockers


class _Orchestrator:
    async def route(self, *_a, **kw):
        return kw.get("route_override") or "general"


class _Step(steps.ProcessorStepsMixin):
    model_id = "m"
    orchestrator = _Orchestrator()


@pytest.fixture()
def spy(monkeypatch):
    """Считает вызовы построения плана и декомпозиции — проверяем ПОВЕДЕНИЕ."""
    calls = {"plan": 0, "decompose": 0}

    async def _plan(*_a, **_kw):
        calls["plan"] += 1
        return "ПЛАН", []

    async def _assess(*_a, **_kw):
        return True

    async def _decompose(*_a, **_kw):
        calls["decompose"] += 1
        return ["шаг 1", "шаг 2"]

    # ⚠️ Патчим ТАМ, ГДЕ ЧИТАЮТ: план резолвится в `pipeline.planning`, декомпозиция
    # зовётся из `processor_steps`.
    from service.domain.pipeline import planning as planning_mod

    monkeypatch.setattr(planning_mod, "build_plan", _plan)
    monkeypatch.setattr(planning_mod, "assess_is_complex", _assess)
    monkeypatch.setattr(steps, "decompose_intents", _decompose)
    return calls


async def _run(route_override, *, planning=True, multi_intent=True):
    return await _Step()._resolve_route_and_plan(
        user_input="разбери файл, сравни подходы и предложи план внедрения",
        thread_id="t",
        route_override=route_override,
        resolved_category="general",
        input_type="text",
        web_search=False,
        deep_research=False,
        multi_intent=multi_intent,
        planning=planning,
        file_context="текст приложенного документа",
        attachments=None,
        meta_usage={},
    )


# --------------------------------------------------------------------------- #
# Планирование                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_general_override_keeps_planning(spy):
    """🔴 ГЛАВНОЕ: приложенный документ больше не отменяет планирование.

    ⚠️ Мульти-интент здесь ВЫКЛЮЧЕН намеренно. Иначе декомпозиция сработает и отменит
    план по своему, законному правилу («декомпозиция и есть план, только исполняемый») —
    тест бы падал, указывая не на ту причину. Первая версия так и падала.
    """
    decision, _events = await _run("general", multi_intent=False)

    assert decision.plan_context == "ПЛАН", (
        "план не построен при служебном форсе general — сообщение с вложением снова "
        "теряет стратегию, которую человек включил явно"
    )


@pytest.mark.asyncio
async def test_real_forced_mode_still_blocks_planning(spy):
    """Настоящий выбор режима планирование по-прежнему отменяет."""
    decision, events = await _run("image_gen", multi_intent=False)

    assert decision.plan_context is None
    assert spy["plan"] == 0
    skipped = [e for e in events if (e.metadata or {}).get("kind") == "plan_skipped"]
    assert skipped and "image_gen" in skipped[0].data


def test_blockers_name_only_real_overrides():
    """Причина отказа не должна называть `general`: иначе текст врёт о выборе человека."""
    plannable = plan_blockers(
        subtasks=None,
        multimodal=False,
        agent_name="general",
        route_override="general",
        web_search=False,
        deep_research=False,
    )
    blocking = plan_blockers(
        subtasks=None,
        multimodal=False,
        agent_name="general",
        route_override="pptx_gen",
        web_search=False,
        deep_research=False,
    )

    assert plannable == "", f"general назван помехой: {plannable!r}"
    assert "pptx_gen" in blocking


# --------------------------------------------------------------------------- #
# Декомпозиция                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_general_override_keeps_decomposition(spy):
    """Тот же критерий и для мульти-интента — иначе «форс general» значит разное."""
    decision, _events = await _run("general")

    assert spy["decompose"] == 1, "декомпозиция не запускалась при служебном форсе general"
    assert decision.subtasks == ["шаг 1", "шаг 2"]


@pytest.mark.asyncio
async def test_real_forced_mode_still_blocks_decomposition(spy):
    decision, _events = await _run("web_search")

    assert spy["decompose"] == 0
    assert decision.subtasks is None
