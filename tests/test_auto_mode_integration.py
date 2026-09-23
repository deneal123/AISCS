"""Оркестратор в конвейере: кого он слушается и когда молчит.

Он управляет ЧЕТЫРЬМЯ рычагами сразу (маршрут, поиск, план, декомпозиция), поэтому
проверяем не «что он вернул», а СКОЛЬКО РАЗ его позвали и что осталось после сбоя.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.application import processor_steps as steps
from service.domain.pipeline import auto_mode
from service.domain.run_context import RunExecutionContext


class _Orchestrator:
    def __init__(self):
        self.calls = 0

    async def route(self, *_a, **kw):
        self.calls += 1
        return kw.get("route_override") or "general"


class _Step(steps.ProcessorStepsMixin):
    model_id = "m"

    def __init__(self):
        self.orchestrator = _Orchestrator()


@pytest.fixture()
def decider(monkeypatch):
    """Счётчик вызовов решателя + управляемый ответ."""
    state = {"calls": 0, "decision": None, "prompts": []}

    async def _decide(user_input, *, prompt_input, model=None, execution=None):
        state["calls"] += 1
        state["prompts"].append(prompt_input)
        return state["decision"]

    # ⚠️ Патчим ТАМ, ГДЕ ЧИТАЮТ: склейка зовёт `decide_modes` из своего модуля.
    monkeypatch.setattr(auto_mode, "decide_modes", _decide)

    async def _plan(*_a, **_kw):
        return "ПЛАН", []

    async def _assess(*_a, **_kw):
        return False

    async def _decompose(*_a, **_kw):
        return ["шаг 1", "шаг 2"]

    from service.domain.pipeline import planning as planning_mod

    monkeypatch.setattr(planning_mod, "build_plan", _plan)
    monkeypatch.setattr(planning_mod, "assess_is_complex", _assess)
    monkeypatch.setattr(steps, "decompose_intents", _decompose)
    return state


def _decision(**kw):
    from service.domain.routing.auto_decision import AutoDecision

    return AutoDecision(**{"route": "general", **kw})


def _confirm(monkeypatch, modes):
    """Подменить НАСТРОЙКУ, а не аргумент: список дорогих режимов шаг читает сам.

    ⚠️ Передать его параметром было бы проще, но тогда тест проверял бы выдуманный
    интерфейс, а не тот, по которому настройка реально доезжает из админки.
    """
    joined = ",".join(sorted(modes))
    monkeypatch.setattr(
        steps, "_agent_flag", lambda name, default: joined if "confirm" in name else default
    )


async def _run(step: _Step, **kw):
    params = {
        "user_input": "разложи задачу по шагам и предложи решение",
        "thread_id": "t",
        "route_override": None,
        "resolved_category": None,
        "input_type": "text",
        "web_search": False,
        "deep_research": False,
        "multi_intent": None,
        "planning": None,
        "file_context": None,
        "attachments": None,
        "execution": RunExecutionContext(),
    }
    params.update(kw)
    return await step._resolve_route_and_plan(**params)


# --------------------------------------------------------------------------- #
# Приоритет выбора человека                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "forced",
    [
        {"route_override": "image_gen"},
        {"web_search": True},
        {"deep_research": True},
        {"input_type": "audio"},
        {"resolved_category": "general"},
    ],
)
@pytest.mark.asyncio
async def test_forced_choice_never_calls_the_decider(decider, forced):
    """🔴 ГЛАВНОЕ: при форсе решатель не вызывается НИ РАЗУ.

    Выбор человека победил бы и ниже по коду, но тогда мы платили бы за решение, которое
    выбрасываем, и однажды кто-нибудь потерял бы приоритет в новой ветке. НЕ ВЫЗЫВАТЬ —
    строго сильнее, чем вызвать и проигнорировать.
    """
    decider["decision"] = _decision(route="deep_research")

    await _run(_Step(), **forced)

    assert decider["calls"] == 0, "заплатили за решение, которое всё равно не применяется"


@pytest.mark.asyncio
async def test_explicit_toggles_are_not_overridden(decider):
    """Тумблеры трёхзначные: сказанное вслух оркестратор не переигрывает."""
    decider["decision"] = _decision(needs_plan=True, multi_step=True)

    decision, _ = await _run(_Step(), planning=False, multi_intent=False)

    assert decision.plan_context is None, "явное «не планировать» переиграно решателем"
    assert decision.subtasks is None


# --------------------------------------------------------------------------- #
# Двойного роутинга не появляется                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_decided_route_replaces_the_old_router(decider):
    """🔴 Один текст роутится ОДИН раз: маршрут от решателя снимает старый вызов."""
    decider["decision"] = _decision(route="general")
    step = _Step()

    await _run(step)

    assert decider["calls"] == 1
    assert step.orchestrator.calls == 0, "роутер позвали вдобавок к решателю — два вызова на текст"


@pytest.mark.asyncio
async def test_failure_falls_back_to_the_old_router(decider):
    """Сбой решателя → маршрут решает прежний роутер. Старый путь И ЕСТЬ фолбэк."""
    decider["decision"] = None
    step = _Step()

    decision, events = await _run(step)

    assert step.orchestrator.calls == 1
    assert decision.agent_name == "general"
    assert not [e for e in events if (e.metadata or {}).get("kind") == "auto_decision"], (
        "показали строку про решение, которого не было"
    )


# --------------------------------------------------------------------------- #
# Стратегии и наблюдаемость                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_decision_turns_on_planning(decider):
    """Ради этого всё и делалось: в «Авто» план включается САМ, без тумблера."""
    decider["decision"] = _decision(needs_plan=True)

    decision, _ = await _run(_Step())

    assert decision.plan_context == "ПЛАН"


@pytest.mark.asyncio
async def test_decision_is_explained_in_the_trace(decider):
    """Отказ прежнего роутера ненаблюдаем вовсе — новый обязан объяснять свой выбор."""
    decider["decision"] = _decision(route="general", needs_plan=True)

    _decision_out, events = await _run(_Step())

    auto = [e for e in events if (e.metadata or {}).get("kind") == "auto_decision"]
    assert auto, "решение принято, а в панели про него ни строки"
    assert auto[0].metadata["auto"]["reason_code"] == "model_classification"
    assert "reason" not in auto[0].metadata["auto"]
    assert auto[0].metadata["auto"]["planning"] is True


@pytest.mark.asyncio
async def test_context_signals_reach_the_prompt(decider):
    """Решатель обязан видеть КОНТЕКСТ — прежний роутер видел только текст сообщения."""
    decider["decision"] = _decision()

    await _run(
        _Step(),
        context=SimpleNamespace(tabular_files=[{"name": "t.csv"}], repo_graph_ids=None),
        history_messages=[{"role": "user", "content": "обсуждали курс биткоина"}],
        compact_summary="тема: криптовалюты",
    )

    prompt = decider["prompts"][0]
    assert "курс биткоина" in prompt and "криптовалюты" in prompt
    assert "табличные данные" in prompt


@pytest.mark.asyncio
async def test_disabled_flag_restores_the_old_path(decider, monkeypatch):
    """Откат — тумблером, а не релизом: выключенный оркестратор = сегодняшний код."""
    monkeypatch.setattr(steps, "_agent_flag", lambda name, default: False)
    decider["decision"] = _decision(route="deep_research")
    step = _Step()

    decision, _ = await _run(step)

    assert decider["calls"] == 0
    assert step.orchestrator.calls == 1
    assert decision.agent_name == "general"


# --------------------------------------------------------------------------- #
# Дорогие режимы: предложение вместо запуска                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_costly_mode_is_offered_not_started(decider, monkeypatch):
    """🔴 ГЛАВНОЕ: глубокое исследование не запускается само.

    Оно стоит тысячи кредитов и идёт минуты. Ошибка решателя здесь — не «ответ вышел
    хуже», а списанные деньги, которых человек не просил.
    """
    decider["decision"] = _decision(route="deep_research", confidence="high")

    _confirm(monkeypatch, {"deep_research"})

    decision, events = await _run(_Step())

    assert decision.agent_name == "general", "дорогой режим стартовал без подтверждения"
    offers = [e for e in events if (e.metadata or {}).get("kind") == "mode_offer"]
    assert offers, "режим не запущен и не предложен — человек не узнает о нём вовсе"
    offer = offers[0].metadata["mode_offer"]
    assert offer["mode"] == "deep_research"
    assert "prompt" not in offer, "исходный вопрос не должен дублироваться в trace metadata"
    assert offer["reason_code"] == "confirmation_required"
    assert "reason" not in offer
    # 🔴 СРОК ЖИЗНИ ЗАДАЁТ СЕРВЕР. Без пары «когда предложено» + «сколько живёт»
    # предложение снова становится бессрочной кнопкой, а отсчёт — браузерным (его
    # переживают перезагрузкой, второй вкладкой и сменой системного времени).
    assert offer["offered_at"], "нет серверной метки времени — отсчёт уедет в браузер"
    assert offer["expires_in_sec"] > 0


@pytest.mark.asyncio
async def test_cheap_mode_starts_without_asking(decider, monkeypatch):
    """Веб-поиск дешёвый: спрашивать про него — трение на ровном месте."""
    decider["decision"] = _decision(route="web_search")

    _confirm(monkeypatch, {"deep_research"})

    decision, events = await _run(_Step())

    assert decision.agent_name == "web_search"
    assert not [e for e in events if (e.metadata or {}).get("kind") == "mode_offer"]


@pytest.mark.asyncio
async def test_explicit_choice_starts_the_costly_mode(decider, monkeypatch):
    """Человек выбрал режим сам — подтверждать нечего, он уже подтвердил."""
    decider["decision"] = _decision(route="deep_research")

    _confirm(monkeypatch, {"deep_research"})

    decision, events = await _run(_Step(), route_override="deep_research")

    assert decision.agent_name == "deep_research"
    assert not [e for e in events if (e.metadata or {}).get("kind") == "mode_offer"]


@pytest.mark.asyncio
async def test_trace_says_the_answer_is_not_in_the_chosen_mode(decider, monkeypatch):
    """Иначе «Режим выбран: глубокое исследование» рядом с обычным ответом = поломка."""
    decider["decision"] = _decision(route="pptx_gen")

    _confirm(monkeypatch, {"pptx_gen"})

    _d, events = await _run(_Step())

    auto = [e for e in events if (e.metadata or {}).get("kind") == "auto_decision"][0]
    assert auto.metadata["auto"]["awaiting_confirmation"] is True


@pytest.mark.asyncio
async def test_empty_confirm_list_starts_everything(decider, monkeypatch):
    """Пустая настройка = «запускать всё самому», а не «спрашивать про всё».

    ⚠️ Но только по ЯВНОЙ просьбе: дорогой режим, выбранный догадкой, всё равно уходит на
    кнопку — см. соседний тест. Пустой список снимает подтверждение, а не осторожность.
    """
    decider["decision"] = _decision(route="deep_research", confidence="high")

    _confirm(monkeypatch, set())

    decision, _events = await _run(_Step())

    assert decision.agent_name == "deep_research"


@pytest.mark.asyncio
async def test_expensive_guess_is_offered_even_with_an_empty_list(decider, monkeypatch):
    """🔴 Догадка на тысячи кредитов не запускается сама даже при пустом списке.

    Админ вправе разрешить автозапуск дорогого режима — он не разрешал списывать за
    предположение. Это же правило прикрывает НОВЫЙ дорогой агент, про который строку в
    админке не обновили: иначе он стартовал бы сам просто потому, что его не перечислили.
    """
    decider["decision"] = _decision(route="deep_research", confidence="low")

    _confirm(monkeypatch, set())

    decision, events = await _run(_Step())

    assert decision.agent_name == "general", "дорогой режим запущен по догадке"
    assert any((e.metadata or {}).get("kind") == "mode_offer" for e in events)


@pytest.mark.asyncio
async def test_decision_turns_on_decomposition_without_conjunctions(decider, monkeypatch):
    """🔴 В «Авто» декомпозиция включается по СМЫСЛУ, а не по наличию слова «затем».

    Тумблер мульти-интента выключен по умолчанию, и вдобавок пре-фильтр требовал союзов —
    то есть в «Авто» разбивка на шаги не работала практически никогда.
    """
    seen = {"force": None}

    async def _decompose(_text, *, force=False, **_kw):
        seen["force"] = force
        return ["шаг 1", "шаг 2"]

    monkeypatch.setattr(steps, "decompose_intents", _decompose)
    decider["decision"] = _decision(multi_step=True)

    decision, _events = await _run(_Step(), user_input="найди статистику и нарисуй график")

    assert decision.subtasks == ["шаг 1", "шаг 2"]
    assert seen["force"] is True, "пре-фильтр по союзам не обойдён — на таких запросах он вето́ит"


@pytest.mark.asyncio
async def test_toggle_alone_does_not_bypass_the_prefilter(decider, monkeypatch):
    """🔴 Тумблер человека пре-фильтр НЕ обходит — иначе «привет» при включённом
    мульти-интенте оплачивало бы вызов декомпозиции на каждом сообщении.

    Обходить его вправе только решатель: он прочитал запрос и знает, что задач несколько.
    Первая версия давала форс и от тумблера — тест это поймал.
    """
    seen = {"force": None}

    async def _decompose(_text, *, force=False, **_kw):
        seen["force"] = force
        return None

    monkeypatch.setattr(steps, "decompose_intents", _decompose)
    decider["decision"] = _decision(multi_step=False)

    await _run(_Step(), multi_intent=True)

    assert seen["force"] is False


@pytest.mark.asyncio
async def test_explicit_multi_intent_false_blocks_model_force(decider):
    """Явный отказ пользователя сильнее model-derived обхода pre-filter."""
    decider["decision"] = _decision(multi_step=True)

    plan = await auto_mode.resolve_auto_plan(
        user_input="две независимые задачи",
        multi_intent=False,
    )

    assert plan.multi_intent is False
    assert plan.force_decompose is False


# --------------------------------------------------------------------------- #
# Телеметрия обхода: без неё прежний роутер нечем удалить                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_bypass_is_counted_with_a_reason(decider):
    """🔴 Каждый обход оркестратора называет ПРИЧИНУ.

    Прежний категорийный роутер удаляется по измерению, а не по решению: когда счётчик
    обхода упадёт до одних только явных выборов человека. Без следа измерять нечего, а лога
    мало — он виден оператору, но не считается по прогонам.
    """
    decider["decision"] = _decision()

    _decision_out, events = await _run(_Step(), route_override="image_gen")

    bypass = [e for e in events if (e.metadata or {}).get("kind") == "legacy_route_used"]
    assert bypass, "обход прежним роутером не посчитан — удалять его будет не по чему"
    assert bypass[0].metadata["reason_code"] == "explicit_route"


@pytest.mark.asyncio
async def test_decider_failure_is_counted_separately(decider):
    """Сбой решателя и штатный обход обязаны различаться в счётчике."""
    decider["decision"] = None

    _decision_out, events = await _run(_Step())

    bypass = [e for e in events if (e.metadata or {}).get("kind") == "legacy_route_used"]
    assert bypass and bypass[0].metadata["reason_code"] == "decision_unavailable"


@pytest.mark.asyncio
async def test_no_bypass_event_when_the_orchestrator_decided(decider):
    """Событие без повода — шум, который научатся не читать."""
    decider["decision"] = _decision(route="general")

    _decision_out, events = await _run(_Step())

    assert not [e for e in events if (e.metadata or {}).get("kind") == "legacy_route_used"]


def test_bypass_kind_is_classified_as_non_usage():
    """⚠️ Вид события без классификации молча считается ОТВЕТОМ и зажигает ложный бейдж."""
    from service.contracts import NON_USAGE_KINDS

    assert "legacy_route_used" in NON_USAGE_KINDS


# --------------------------------------------------------------------------- #
# Workflow: объявленная цепочка вместо выпрошенной у модели                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_declared_workflow_becomes_subtasks(decider, monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА. Реестр может знать workflow, а конвейер — не разворачивать его.

    Проверяем не спеку, а результат шага: выбранный маршрут-цепочка обязан превратиться в
    подзадачи, которые дальше исполнит тот же `execute_steps`, что и декомпозицию.
    """
    decider["decision"] = _decision(route="research_deck", confidence="high")
    _confirm(monkeypatch, set())  # снимаем подтверждение, иначе цепочка уйдёт на кнопку

    decision, _events = await _run(_Step())

    assert decision.subtasks is not None, "workflow выбран, но в подзадачи не развёрнут"
    assert [t.category for t in decision.subtasks] == ["deep_research", "pdf_gen"]


@pytest.mark.asyncio
async def test_workflow_does_not_pay_for_decomposition(decider, monkeypatch):
    """Объявленная цепочка не выпрашивается у модели: вызова декомпозиции быть не должно."""
    called = {"n": 0}

    async def _decompose(*_a, **_kw):
        called["n"] += 1
        return ["шаг"]

    monkeypatch.setattr(steps, "decompose_intents", _decompose)
    decider["decision"] = _decision(route="research_deck", confidence="high", multi_step=True)
    _confirm(monkeypatch, set())

    await _run(_Step())

    assert called["n"] == 0, "за готовую цепочку заплатили вызовом декомпозиции"


# --------------------------------------------------------------------------- #
# Понижённый ответ не обещает того, чего не делает                              #
# --------------------------------------------------------------------------- #
def test_declined_mode_is_appended_deterministically():
    """🔴 ПРОСЬБУ В ПРОМПТЕ МОДЕЛЬ ИГНОРИРУЕТ — проверено живым прогоном.

    Системная оговорка «режим не запускался, не обещай его выполнить» не сработала: ответ
    всё равно начинался с «я проведу исследование…», хотя ресёрч предложен кнопкой, и человек
    видел кнопку рядом с текстом, который ей противоречит. Тот же урок, что с оговорками
    личностей: текст такого класса дописывается детерминированно, а не выпрашивается.
    """
    from service.application.use_cases.agent_execution_use_cases import _note_declined_mode

    out = _note_declined_mode("Вот план исследования.", {"mode_offer": {"label": "ресёрч"}})

    assert "не запускался" in out and "ресёрч" in out
    assert out.startswith("Вот план исследования."), "ответ модели потерян"
    # 🔴 ПРИПИСКА НЕ НАЗЫВАЕТ СТОРОНУ. Здесь стояло «кнопкой выше», а карточка рисуется
    # ПОД текстом: указание врало ровно там, где должно было помочь. Разметки отсюда не
    # видно — значит и утверждать о взаимном расположении нельзя.
    assert "выше" not in out and "ниже" not in out
    # ⚠️ И не повторяет карточку: цену и кнопку она называет сама.
    assert "дорог" not in out and "кнопк" not in out


def test_no_note_when_nothing_was_declined():
    """Приписка без повода — шум под каждым ответом."""
    from service.application.use_cases.agent_execution_use_cases import _note_declined_mode

    assert _note_declined_mode("обычный ответ", {}) == "обычный ответ"


def test_no_double_note_when_the_model_said_it_itself():
    """Если модель сказала сама — не дублируем."""
    from service.application.use_cases.agent_execution_use_cases import _note_declined_mode

    text = "Полноценный ресёрч не запускался, но вот что я могу сам."

    assert _note_declined_mode(text, {"mode_offer": {"label": "ресёрч"}}) == text


@pytest.mark.asyncio
async def test_offer_reaches_the_context(decider, monkeypatch):
    """Точка вызова: план обязан донести отклонённый режим до контекста ответа."""
    from types import SimpleNamespace

    decider["decision"] = _decision(route="deep_research", confidence="high")
    _confirm(monkeypatch, {"deep_research"})
    context = SimpleNamespace(
        declined_mode=None,
        web_tool_enabled=False,
        tabular_files=None,
        repo_graph_ids=None,
        reference_image_url=None,
        has_non_tabular_attachment=False,
    )

    await _run(_Step(), context=context)

    from service.domain.run_context import require_execution

    assert require_execution().policy.values["declined_mode"] == "deep_research"
