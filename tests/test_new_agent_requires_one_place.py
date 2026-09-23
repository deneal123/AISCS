"""Добавление субагента требует ОДНОГО места — и это проверяется, а не обещается.

⚠️ ЗАЧЕМ. Знание об агенте жило в девяти независимых литеральных списках: фабрика,
`ALLOWED_CATEGORIES`, `_ALLOWED_FORCED_CATEGORIES`, `_VALID_TOOLS`, `_ROUTE_LABELS`,
категории в промпте декомпозиции, блок маршрутов в `AUTO_PROMPT`, `BILLABLE_TOOLS` и разбор
`auto_tool` в use-case. Пропуск любого НЕ давал ни ошибки, ни лога:

- забыт в промпте декомпозиции → агент молча выпадал из мульти-интента;
- забыт в `_ROUTE_LABELS` → человек видел в трейсе машинное имя;
- забыт в `AUTO_PROMPT` → для оркестратора агента просто не существовало;
- забыт в `BILLABLE_TOOLS` → работа шла, деньги не списывались.

Тест объявляет фиктивного агента ЦЕЛИКОМ ВНУТРИ СЕБЯ — одна спека и модуль в три строки —
и не правит ни строчки прода. Заведут десятый список — покраснеет: dummy в него не попадёт.

Приём тот же, что у `tests/test_new_provider_requires_one_place.py`, и это намеренно:
доктрина одна, значит и проверка должна читаться одинаково.
"""

from __future__ import annotations

import sys
import types

import pytest

from service.domain.capabilities import agent_spec as spec_mod
from service.domain.capabilities import derived, registry

DUMMY_PATH = "service.domain.subagents.dummy_for_test"
MODAL_PATH = "service.domain.subagents.dummy_modal_for_test"


@pytest.fixture
def orchestrator_off(monkeypatch):
    """Выключить оркестратор: разбор догадки роутера моделей — его ФОЛБЭК."""
    from service.application.use_cases import agent_execution_use_cases as uc

    monkeypatch.setattr(uc, "_orchestrator_enabled", lambda: False)


class _DummyAgent:
    def __init__(self, model_settings: dict):
        self.model_settings = model_settings


DUMMY = spec_mod.AgentSpec(
    name="dummy",
    label_ru="фиктивный режим",
    build=_DummyAgent,
    billing_name="dummy",
    cost_class=spec_mod.COST_EXPENSIVE,
    confirm_by_default=True,
    prompt_hint="фиктивный маршрут, существует только внутри теста.",
)

# ⚠️ Второй фиктивный агент нужен ради ОДНОГО свойства — требования модальности. Модальность
# у нас сегодня требует ровно один настоящий агент (`audio_transcribe`), и проверка на нём
# не отличила бы «правило выводится из спеки» от «в коде написано `== "audio_transcribe"`».
# Поэтому модальность здесь заведомо ДРУГАЯ.
DUMMY_MODAL = spec_mod.AgentSpec(
    name="dummy_modal",
    label_ru="фиктивный модальный режим",
    build=_DummyAgent,
    routable=False,
    decomposable=False,
    requires_input_type="video",
    forced_by_input_type=("video",),
    input_type_beats_toggles=True,
)


@pytest.fixture
def dummy_agent(monkeypatch):
    """Зарегистрировать агентов ТАК ЖЕ, как это сделал бы новый файл в `subagents/`.

    ⚠️ Модуль кладётся в `sys.modules`, а путь — в источники реестра. Вписать спеку прямо в
    словарь было бы проще, но тогда тест проверял бы свою подмену, а не то, что реестр
    действительно выводится из объявленных модулей.
    """
    for path, spec in ((DUMMY_PATH, DUMMY), (MODAL_PATH, DUMMY_MODAL)):
        module = types.ModuleType(path)
        module.SPEC = spec
        monkeypatch.setitem(sys.modules, path, module)
    monkeypatch.setattr(
        registry,
        "_AGENT_SOURCES",
        (*registry._AGENT_SOURCES, DUMMY_PATH, MODAL_PATH),
        raising=True,
    )


# --------------------------------------------------------------------------- #
# Реестр                                                                        #
# --------------------------------------------------------------------------- #
def test_registry_resolves_the_new_agent(dummy_agent):
    assert registry.get_spec("dummy") is DUMMY
    assert "dummy" in registry.agent_specs()


def test_agent_is_built_by_the_factory(dummy_agent):
    """Фабрика собирает объявленное, а не перечисленное вручную."""
    from service.domain.subagents.factory import build_subagents

    agents = build_subagents({"model": "x"})

    assert isinstance(agents["dummy"], _DummyAgent)
    assert agents["dummy"].model_settings == {"model": "x"}


# --------------------------------------------------------------------------- #
# Девять бывших списков                                                         #
# --------------------------------------------------------------------------- #
def test_route_vocabulary_includes_the_new_agent(dummy_agent):
    """Иначе роутер не вправе вернуть категорию — и молча отдаёт `general`."""
    assert "dummy" in derived.route_vocabulary()


def test_orchestrator_decision_keeps_the_new_route(dummy_agent):
    """Разбор ответа оркестратора отбрасывает маршрут вне словаря.

    ⚠️ Деградация здесь ПОФИЛЬНАЯ и тихая по замыслу: неизвестный маршрут обнуляется, а
    стратегии остаются. Значит новый агент, не попавший в словарь, выглядел бы как «модель
    его не выбрала» — при том, что она его выбрала.
    """
    from service.domain.routing.auto_decision import normalize_decision

    decision = normalize_decision({"route": "dummy", "confidence": "high"})

    assert decision is not None
    assert decision.route == "dummy"


def test_decomposition_accepts_a_step_of_the_new_agent(dummy_agent):
    """🔴 Фильтр разбора подзадач — это и есть место, где агент выпадал молча.

    Проверяем НАСТОЯЩИЙ разбор ответа модели, а не рендер словаря: снимок словаря,
    вычисленный на импорте, фиктивного агента увидеть не может, и проверка была бы слепа.
    """
    from service.domain.pipeline.decomposition import _parse_subtasks

    tasks = _parse_subtasks('[{"category": "dummy", "instruction": "сделай", "independent": true}]')

    assert [t.category for t in tasks] == ["dummy"]


def test_forced_allowlist_includes_the_new_agent(dummy_agent):
    """Иначе тумблер человека не действует: `route_override` отбрасывается молча."""
    from service.domain.routing.policy import resolve_forced_category

    assert "dummy" in derived.forced_allowlist()
    assert (
        resolve_forced_category(
            route_override="dummy", input_type=None, web_search=False, deep_research=False
        )
        == "dummy"
    )


def test_router_tool_vocabulary_includes_the_new_agent(dummy_agent):
    """Роутер моделей отдаёт `tool`; неизвестное значение он отбрасывает."""
    assert "dummy" in derived.valid_router_tools()


def test_decompose_prompt_includes_the_new_agent(dummy_agent):
    """🔴 Самый тихий из девяти: агент просто не появлялся в мульти-интенте."""
    from service.domain.pipeline.decomposition import _decompose_prompt

    assert "dummy" in _decompose_prompt()


def test_trace_label_exists_for_the_new_agent(dummy_agent):
    """Иначе человек видит в трейсе машинное имя вместо режима."""
    from service.domain.pipeline.auto_mode import _offer_event
    from service.domain.routing.auto_decision import AutoDecision

    event = _offer_event(AutoDecision(route="dummy"), "dummy", "вопрос")

    assert event.metadata["mode_offer"]["label"] == "фиктивный режим"


def test_auto_prompt_offers_the_new_agent(dummy_agent):
    """Иначе для оркестратора агента не существует: выбрать его он не может."""
    from service.domain.routing.auto_prompt import auto_prompt

    text = auto_prompt()

    assert "- dummy — фиктивный маршрут" in text
    assert "|dummy" in text, "маршрут не попал в JSON-схему ответа"


def test_modality_requirement_is_honoured_for_the_new_agent(dummy_agent, orchestrator_off):
    """Маршрут, которому нужна модальность, без неё сбрасывается — во ВСЕХ трёх местах.

    ⚠️ Правило жило тремя независимыми копиями: `_guard_tool_modality`, `Orchestrator.route`
    и разбор `auto_tool` в use-case. Две из них — защита в глубину, и это осмысленно; но
    списки допустимых модальностей у них расходились бы молча.
    """
    from service.application.use_cases.agent_execution_use_cases import (
        PrepareExecutionContextUseCase,
    )
    from service.domain.tools.router import _guard_tool_modality

    assert _guard_tool_modality("dummy_modal", "text") == "none"
    assert _guard_tool_modality("dummy_modal", "video") == "dummy_modal"

    result = PrepareExecutionContextUseCase().execute(
        routing_meta={"tool": "dummy_modal"},
        route_override=None,
        resolved_category=None,
        web_search=False,
        deep_research=False,
        session_data=None,
        thread_id="t",
        pseudo_session=None,
        input_type="text",
    )
    # Не `None`: сброс уводит на `general` — обычный ответ вместо эха расшифровки.
    assert result["route_override"] == "general"


def test_input_type_forces_the_new_agent(dummy_agent):
    """Модальность форсит маршрут сама по себе и побеждает тумблер человека."""
    from service.domain.routing.policy import resolve_forced_category

    assert (
        resolve_forced_category(
            route_override=None, input_type="video", web_search=False, deep_research=True
        )
        == "dummy_modal"
    )


def test_billing_name_reaches_the_surcharge_set(dummy_agent):
    """Иначе агент работает, а деньги не списываются."""
    assert "dummy" in derived.billing_names()


def test_confirm_policy_covers_the_expensive_agent(dummy_agent):
    """Дорогой режим по умолчанию требует кнопки, а не запускается сам."""
    assert "dummy" in derived.confirm_default_names()


def test_use_case_expands_the_new_route(dummy_agent, orchestrator_off):
    """Разбор `auto_tool` в use-case — девятое место, и оно тоже выводится.

    ⚠️ Путь ФОЛБЭЧНЫЙ: догадка роутера моделей разворачивается только при выключенном
    оркестраторе. При включённом она молча перехватывала бы у него управление.
    """
    from service.application.use_cases.agent_execution_use_cases import (
        PrepareExecutionContextUseCase,
    )

    result = PrepareExecutionContextUseCase().execute(
        routing_meta={"tool": "dummy"},
        route_override=None,
        resolved_category=None,
        web_search=False,
        deep_research=False,
        session_data=None,
        thread_id="t",
        pseudo_session=None,
        input_type="text",
    )

    assert result["route_override"] == "dummy"


# --------------------------------------------------------------------------- #
# Целостность деклараций                                                        #
# --------------------------------------------------------------------------- #
def test_every_enabled_field_exists_in_settings():
    """⚠️ Спека адресует поле `AgentsConfig` ПО ИМЕНИ — опечатка тут тихая.

    Чтение идёт через `getattr(..., None)`: несуществующее имя даёт None, и агент молча
    выглядит выключенным. Ошибки при этом нет нигде.
    """
    from service.settings import AgentsConfig

    declared = set(AgentsConfig.model_fields)
    missing = [
        f"{s.name}.{s.enabled_field}"
        for s in registry.agent_specs().values()
        if s.enabled_field and s.enabled_field not in declared
    ]

    assert not missing, f"спеки ссылаются на несуществующие поля настроек: {missing}"


def test_billable_tools_contract_matches_the_registry():
    """`contracts.BILLABLE_TOOLS` — литерал, и это осознанно.

    ⚠️ Модуль контрактов обязан импортироваться БЕЗ домена: его в одиночку грузит офлайн-гейт
    парити, сверяющий набор с прайсом backend'а. Поэтому вывести множество из реестра там
    нельзя — вместо этого расхождение ловит эта проверка.
    """
    from service.contracts import BILLABLE_TOOLS

    agent_names = derived.billing_names()
    missing = sorted(agent_names - set(BILLABLE_TOOLS))
    assert not missing, f"агенты тарифицируются, но не заявлены в BILLABLE_TOOLS: {missing}"


def test_confirm_modes_default_matches_the_registry():
    """Дефолт настройки и объявления агентов не должны расходиться.

    Настройка — строка в админке, и её значение по умолчанию живёт в `AgentsConfig`. Разойдись
    оно со спеками — дорогой режим либо запускался бы сам, либо навсегда требовал кнопки.
    """
    from service.settings import AgentsConfig

    default = AgentsConfig.model_fields["auto_confirm_modes"].default
    declared = {part.strip() for part in str(default).split(",") if part.strip()}

    assert declared == derived.confirm_default_names()


# --------------------------------------------------------------------------- #
# Workflow-агенты: тот же словарь маршрутов, никакой своей машинерии             #
# --------------------------------------------------------------------------- #
def test_workflow_shares_the_route_vocabulary():
    """Оркестратор выбирает ОДИН идентификатор и не знает, агент это или цепочка."""
    from service.domain.capabilities import get_workflow

    assert "research_pdf_presentation" in derived.route_vocabulary()
    assert get_workflow("research_pdf_presentation") is not None
    assert derived.route_labels()["research_pdf_presentation"] == "исследование и PDF-презентация"


def test_workflow_instantiates_into_plain_subtasks():
    """🔴 Главное свойство: workflow — это ДАННЫЕ, а не движок.

    Он разворачивается в те же `SubTask`, что вернула бы декомпозиция, и исполняется тем же
    `execute_steps`. Появись у него своя машинерия — её пришлось бы чинить дважды, и
    объявленный сценарий начал бы вести себя иначе, чем разобранный моделью.
    """
    from service.domain.capabilities import get_workflow
    from service.domain.pipeline.decomposition import SubTask

    steps = get_workflow("research_pdf_presentation").instantiate("рынок ИИ")

    assert all(isinstance(s, SubTask) for s in steps)
    assert [s.category for s in steps] == ["deep_research", "pdf_gen"]
    assert "рынок ИИ" in steps[0].instruction, "запрос человека не доехал до шага"
    assert steps[1].independent is False, "второй шаг обязан видеть вывод первого"


def test_expensive_workflow_is_confirm_gated():
    """Цепочка дороже одиночного агента — ворота стоимости обязаны действовать и на неё."""
    assert "research_pdf_presentation" in derived.confirm_default_names()


def test_workflow_spec_stays_serialisable():
    """⚠️ В спеке только строки, числа и булевы — и это условие БУДУЩЕЙ автономности.

    Спеки предстоит сочинять самому агенту, сохранять и передавать в теле запроса. Появись
    в ней callable — сочинённую спеку нельзя будет ни сохранить, ни прислать, и вся ветка
    автосборки упрётся в это молча.
    """
    import dataclasses

    from service.domain.capabilities import get_workflow

    payload = dataclasses.asdict(get_workflow("research_pdf_presentation"))

    import json

    json.dumps(payload, ensure_ascii=False)


def test_model_router_guess_does_not_preempt_the_orchestrator(dummy_agent):
    """🔴 Роутер моделей молча перехватывал управление у «умного Авто».

    Его вердикт `tool` разворачивался во флаги, а флаги неотличимы от выбора человека — и на
    выбор человека оркестратор не вызывается ВООБЩЕ. То есть маршрут решал он, видя только
    текст: без контекста, истории и формы вложений, ради которых оркестратор и заводился.
    """
    from service.application.use_cases.agent_execution_use_cases import (
        PrepareExecutionContextUseCase,
    )

    result = PrepareExecutionContextUseCase().execute(
        routing_meta={"tool": "web_search"},
        route_override=None,
        resolved_category=None,
        web_search=False,
        deep_research=False,
        session_data=None,
        thread_id="t",
        pseudo_session=None,
        input_type="text",
    )

    assert result["web_search"] is False, "догадка роутера моделей снова блокирует оркестратор"
    assert result["route_override"] is None


def test_human_choice_still_reaches_the_pipeline():
    """Контроль: выбор ЧЕЛОВЕКА проходит насквозь и при включённом оркестраторе."""
    from service.application.use_cases.agent_execution_use_cases import (
        PrepareExecutionContextUseCase,
    )

    result = PrepareExecutionContextUseCase().execute(
        routing_meta={"tool": "none"},
        route_override=None,
        resolved_category=None,
        web_search=True,
        deep_research=False,
        session_data=None,
        thread_id="t",
        pseudo_session=None,
        input_type="text",
    )

    assert result["web_search"] is True
