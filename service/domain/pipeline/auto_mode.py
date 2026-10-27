"""Склейка авто-оркестратора с конвейером: что он решает и чего не трогает.

Отдельным модулем, а не веткой в шагах: решение о режимах — самостоятельная тема, и его
видно целиком, только пока оно лежит одним куском.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from service.domain.capabilities import (
    COST_EXPENSIVE,
    get_spec,
    route_labels,
)
from service.domain.execution.context import RunExecutionContext, require_execution
from service.domain.pipeline.confirmation import offer_ttl_sec
from service.domain.pipeline.confirmation import tool_offer_event as _tool_offer_event
from service.domain.pipeline.video_offer import _mentions_a_video, _video_offer_allowed
from service.domain.routing.auto.decision import (
    CONFIDENCE_HIGH,
    REASON_SHORTCUT_SMALLTALK,
    SOURCE_SHORTCUT,
    AutoDecision,
)
from service.domain.routing.auto.router import decide_modes
from service.domain.routing.auto.signals import build_auto_input
from service.domain.routing.policy import canonical_route
from service.events import AgentEvent, EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AutoPlan:
    """Что оркестратор сообщает конвейеру. `None` в поле — «решай как раньше»."""

    route_hint: str | None = None
    planning: bool | None = None
    multi_intent: bool | None = None
    web_tool: bool = False
    files_tool: bool = False
    # 🔴 Обходить regex-пре-фильтр вправе только РЕШАТЕЛЬ, не тумблер: иначе «привет»
    # при включённом мульти-интенте оплачивало бы вызов декомпозиции.
    force_decompose: bool = False
    # Дорогой режим, который НЕ запущен и предложен кнопкой. Ответу нужно об этом знать.
    offered_mode: str | None = None
    # То же для дорогого ИНСТРУМЕНТА. Отдельное поле, а не общее с режимом: принимаются
    # они по-разному — режим перезапускает прогон маршрутом, инструмент лишь снимает
    # запор с признака контекста. Свалив их в одно поле, мы получили бы `route_override`
    # с именем, которого среди маршрутов нет.
    offered_tool: str | None = None
    events: list[AgentEvent] = field(default_factory=list)

    @staticmethod
    def passthrough(reason_code: str = "", *, files_tool: bool = False) -> AutoPlan:
        """Оркестратор не участвует: всё поведение ровно сегодняшнее.

        ⚠️ Причина уезжает СОБЫТИЕМ, а не в лог. Прежний роутер удаляется по измерению —
        когда счётчик обхода упадёт до одних только явных выборов человека, — и без следа
        измерять было бы нечего.
        """
        return AutoPlan(
            events=[_legacy_route_event(reason_code)] if reason_code else [],
            # ⚠️ Даже когда оркестратор не участвует, ПРЯМАЯ просьба человека действует:
            # «воспользуйся workspace» не должно молчать из-за выключенной настройки или
            # заблокированной ветки.
            files_tool=files_tool,
        )


def _blocking_reason_code(
    *,
    route_override: str | None,
    input_type: str | None,
    web_search: bool,
    deep_research: bool,
    multimodal: bool,
    resolved_category: str | None,
) -> str | None:
    """Почему оркестратор не должен вызываться. `None` — можно решать.

    🔴 Приоритет форса гарантируется НЕИСПОЛНЕНИЕМ: выбор человека победил бы и ниже, но
    тогда мы платили бы за выброшенное решение, а новая ветка однажды потеряла бы
    приоритет.
    """
    if route_override:
        return "explicit_route"
    if web_search or deep_research:
        return "explicit_search"
    if input_type and input_type != "text":
        return "nontext_input"
    if multimodal:
        return "multimodal_input"
    if resolved_category:
        # REST-путь уже заплатил за решение в `/route`; живой чат туда не ходит вовсе.
        return "pre_resolved_route"
    return None


def _legacy_route_event(reason_code: str) -> AgentEvent:
    """Оркестратор обойдён — маршрут решает прежний категорийный роутер."""
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data="",
        metadata={"kind": "legacy_route_used", "reason_code": reason_code},
    )


def _offer_event(decision: AutoDecision, mode: str, _user_input: str) -> AgentEvent:
    """Предложение запустить дорогой режим — кнопкой, а не молча.

    🔴 ОТСЧЁТ АНКЕРИТСЯ НА СЕРВЕРНЫХ ЧАСАХ (`offered_at`), а не на клиентских. Таймер в
    браузере переживают перезагрузкой, второй вкладкой и просто сменой системного
    времени; решение о тысячах кредитов от этого зависеть не может. Клиент по этим двум
    полям только РИСУЕТ остаток, а истечение проверяет сервер (см.
    `chat_persistence_service._expire_mode_offer`).

    ⚠️ Молчание = ОТКАЗ. Автозапуск по таймауту означал бы списание тысяч кредитов у
    человека, который отошёл от экрана.
    """
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data=f"Предложен режим: {route_labels().get(mode, mode)}",
        metadata={
            "kind": "mode_offer",
            "mode_offer": {
                "mode": mode,
                "blocking": True,
                "label": route_labels().get(mode, mode),
                "reason_code": "confirmation_required",
                "confidence": decision.confidence,
                "offered_at": datetime.now(UTC).isoformat(),
                "expires_in_sec": offer_ttl_sec(),
            },
        },
    )


def _decision_event(
    decision: AutoDecision,
    plan: dict[str, Any],
    *,
    offered: bool = False,
    reason_code: str | None = None,
) -> AgentEvent:
    """Строка трейса: почему он поступил так. Отказ прежнего роутера был ненаблюдаем —
    он молча отдавал `general`."""
    label = route_labels().get(decision.route or "", decision.route or "обычный ответ")
    extras = [
        name for name, on in (("план", plan.get("planning")), ("поиск", plan.get("web_tool"))) if on
    ]
    if plan.get("multi_intent"):
        extras.append("разбивка на шаги")
    title = f"Режим выбран: {label}" + (f" · {' · '.join(extras)}" if extras else "")
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="router",
        data=title,
        metadata={
            "kind": "auto_decision",
            "auto": {
                "route": decision.route,
                "source": decision.source,
                "confidence": decision.confidence,
                "reason_code": reason_code or decision.reason_code,
                # Иначе «Режим выбран: глубокое исследование» рядом с обычным ответом
                # читается как поломка.
                "awaiting_confirmation": offered,
                **plan,
            },
        },
    )


def _needs_confirmation(route: str, confidence: str, admin_modes: str) -> bool:
    """Запускать ли дорогой режим самому или предложить кнопкой.

    Два правила:

    1. Список из админки — авторитетен, включая ПУСТОЙ: пустой означает «запускать всё
       самому», а не «спрашивать про всё». Это осознанный аварийный тумблер.
    2. 🔴 Но дорогой режим ВНЕ списка всё равно требует ВЫСОКОЙ уверенности. Админ вправе
       разрешить автозапуск — он не разрешал списывать тысячи кредитов по ДОГАДКЕ. Это же
       правило прикрывает новый дорогой агент, про который строку в админке не обновили:
       без него он начал бы запускаться сам просто потому, что его там не перечислили.
    """
    # Persisted/admin values may still contain the S34 compatibility routes
    # (``pptx_gen``/``research_deck``).  Apply the same canonicalization as the
    # router so an old allowlist cannot silently unlock the replacement PDF route.
    confirm = {
        canonical_route(part.strip()) for part in str(admin_modes or "").split(",") if part.strip()
    }
    if route in confirm:
        return True
    spec = get_spec(route)
    return bool(spec and spec.cost_class == COST_EXPENSIVE and confidence != CONFIDENCE_HIGH)


# 🔴 ЯВНАЯ ПРОСЬБА ЧЕЛОВЕКА СИЛЬНЕЕ РЕШЕНИЯ МОДЕЛИ. Живой прогон: на «воспользуйся
# workspace» оркестратор не поставил `needs_files`, инструменты не выдались, и ассистент
# ответил, что доступа к файлам у него нет. Спорить с прямой просьбой нельзя, а полагаться
# на то, что решающая модель распознает КАЖДУЮ формулировку, — нельзя тем более: тот же
# урок, что с оговорками у личностей, где помогло только детерминированное правило.
_FILES_WORDS = (
    "workspace",
    "воркспейс",
    "песочниц",
    "рабочем месте",
    "рабочее место",
    "рабочей области",
    "рабочую область",
    "рабочем каталоге",
    "рабочий каталог",
    "запусти код",
    "выполни код",
    "выполни команду",
    "запусти скрипт",
    "собери файл",
    "создай файл",
    "создать файл",
    "сохрани в файл",
    "запиши в файл",
    "обнови файл",
    "измени файл",
)


# 🔴 ССЫЛКУ НА ВИДЕО УЗНАЁМ ДЕТЕРМИНИРОВАННО, а не решением модели. Тот же урок, что с
# файловыми инструментами и оговорками у личностей: полагаться на то, что решатель опознает
# КАЖДУЮ форму ссылки, нельзя, а цена промаха здесь — «посмотри этот ролик» без просмотра.
# ⚠️ Список хостов НЕ претендует на полноту: он лишь повод ПРЕДЛОЖИТЬ кнопку. Ошибка в
# сторону «не предложили» стоит одного уточняющего сообщения, а в сторону «предложили зря»
# — ничего, потому что запускает человек.
def _explicitly_asks_for_files(user_input: str) -> bool:
    """Человек прямым текстом попросил файловые инструменты."""
    text = str(user_input or "").lower()
    return any(word in text for word in _FILES_WORDS)


def _code_is_unreadable_without_tools(is_map: bool) -> bool:
    """Приложен архив с кодом: без файловых инструментов прочитать его НЕЧЕМ.

    🔴 ПРАВИЛО КОДА, А НЕ ПРОСЬБА К РЕШАТЕЛЮ, и на это ушло пять замеров. Формулировку в
    промпте я правил трижды, включая явное «это правило сильнее списка false» — решатель на
    «покажи код функции Session.request и объясни построчно» ВСЁ РАВНО отвечал
    `files_tool: false`. Инструментов у модели не оставалось, и она восемь раз ходила за
    кодом в интернет, обещая «сейчас найду в локальных файлах». Ответа человек не получал.

    Спорить с решателем бессмысленно там, где ответ известен заранее: если в контексте
    только КАРТА репозитория (имена и связи, без единой строки кода), то прочитать код
    можно ИСКЛЮЧИТЕЛЬНО инструментом. Это не оценка намерения, а факт о наличии данных —
    ровно такие вещи и решаются кодом.

    ⚠️ Цена честная и небольшая: девять схем `ws_*` в промпте, но только когда приложен
    архив, а это редкий случай. Когда он приложен, работа с файлами нужна почти всегда —
    иначе агент выдаёт пересказ имён файлов вместо ответа. Обычный чат не затронут: там
    карты нет, и признак ложен.

    ⚠️ Текст промпта при этом ОСТАВЛЕН: он объясняет модели, ЧТО делать с полученными
    инструментами. Правило решает лишь то, будут ли они у неё вообще.
    """
    return bool(is_map)


def apply_plan(
    plan: AutoPlan,
    *,
    context: Any,
    multi_intent: bool | None,
    planning: bool | None,
    resolved_category: str | None,
    execution: RunExecutionContext | None = None,
) -> tuple[bool | None, bool | None, str | None]:
    """Наложить решение оркестратора на параметры прогона.

    ⚠️ Тумблеры трёхзначные: `None` означает «не сказано вслух», и только его оркестратор
    вправе заполнить. Сказанное человеком остаётся как есть.

    ⚠️ `web_tool_enabled` дописывается в УЖЕ СОБРАННЫЙ контекст: решение о свежих данных
    принимается после его сборки, а инструмент поиска выдаётся по этому признаку.
    """
    from service.domain.execution.context import GroundingReason, require_execution, set_policy_flag

    execution = require_execution(execution)

    if context is not None and plan.web_tool:
        set_policy_flag(context, "web_tool_enabled", True)
        if execution.policy.grounding_reason is GroundingReason.NONE:
            execution.policy.grounding_reason = GroundingReason.FRESH_DATA
    # 🔴 Файловые инструменты — ТОЛЬКО когда оркестратор сказал «нужны файлы» И песочница
    # выдана. Два условия сходятся в ОДИН признак: у спеки инструмента гейт один, и
    # разносить его по двум местам значило бы однажды проверить только одно.
    if context is not None and plan.files_tool and getattr(context, "workspace_ref", None):
        set_policy_flag(context, "workspace_tools_enabled", True)
    if context is not None and plan.offered_mode:
        from service.domain.execution.context import set_policy_value

        set_policy_value(context, "declined_mode", plan.offered_mode)
    return (
        plan.multi_intent if plan.multi_intent is not None else multi_intent,
        plan.planning if plan.planning is not None else planning,
        plan.route_hint or resolved_category,
    )


def _unavailable_decision_plan(user_input, context, execution, explicit_files) -> AutoPlan:
    fallback = AutoPlan.passthrough("decision_unavailable", files_tool=explicit_files)
    if (
        not execution.policy.flag("confirmation_declined")
        and not getattr(context, "video_tool_enabled", False)
        and _mentions_a_video(user_input)
        and _video_offer_allowed()
    ):
        return replace(
            fallback,
            offered_tool="watch_video",
            events=[
                *fallback.events,
                _tool_offer_event(
                    "watch_video", "просмотр видео", "video_confirmation_required", user_input
                ),
            ],
        )
    return fallback


def _is_smalltalk(decision: AutoDecision) -> bool:
    return (
        decision.source == SOURCE_SHORTCUT
        and decision.reason_code == REASON_SHORTCUT_SMALLTALK
        and decision.route == "general"
    )


def _apply_file_grounding(execution, user_input, context, text_present, text_is_map):
    """Set deterministic source requirements before optional model routing."""
    from service.domain.execution.context import GroundingReason

    explicit_request = _explicitly_asks_for_files(user_input)
    explicit_files = explicit_request or _code_is_unreadable_without_tools(text_is_map)
    if explicit_files:
        execution.policy.grounding_reason = (
            GroundingReason.WORKSPACE_EXPLICIT
            if explicit_request
            else GroundingReason.WORKSPACE_SOURCE_ONLY
        )
    elif bool(getattr(context, "tabular_files", None)) and not text_present:
        execution.policy.grounding_reason = GroundingReason.TABULAR_SOURCE_ONLY
    return explicit_files


async def resolve_auto_plan(
    *,
    user_input: str,
    context: Any = None,
    history_messages: Any = None,
    compact_summary: str | None = None,
    route_override: str | None = None,
    input_type: str | None = None,
    web_search: bool = False,
    deep_research: bool = False,
    multimodal: bool = False,
    resolved_category: str | None = None,
    attachments: Any = None,
    multi_intent: bool | None = None,
    planning: bool | None = None,
    enabled: bool = True,
    confirm_modes: str = "",
    model: str | None = None,
    execution: RunExecutionContext | None = None,
    attachment_text_in_prompt: bool = False,
    attachment_text_in_prompt_is_a_map: bool = False,
) -> AutoPlan:
    execution = require_execution(execution)
    execution.policy.set_flag("ordinary_conversation", False)
    explicit_files = _apply_file_grounding(
        execution,
        user_input,
        context,
        attachment_text_in_prompt,
        attachment_text_in_prompt_is_a_map,
    )
    if not enabled:
        return AutoPlan.passthrough("disabled", files_tool=explicit_files)
    if reason_code := _blocking_reason_code(
        route_override=route_override,
        input_type=input_type,
        web_search=web_search,
        deep_research=deep_research,
        multimodal=multimodal,
        resolved_category=resolved_category,
    ):
        logger.debug("Авто-оркестратор не вызывается: %s", reason_code)
        return AutoPlan.passthrough(reason_code, files_tool=explicit_files)

    persona_labels: list[str] = []
    try:
        from service.domain import persona

        persona_labels = list(persona.current().ids)
    except Exception:  # noqa: BLE001 — личности необязательны, без них решение хуже, но есть
        logger.debug("persona labels unavailable", extra={"failure_code": "unavailable"})

    prompt_input = build_auto_input(
        user_input=user_input,
        today=datetime.now(UTC).date().isoformat(),
        history_messages=history_messages,
        compact_summary=compact_summary or "",
        attachments=attachments,
        has_tables=bool(getattr(context, "tabular_files", None)),
        has_repo_graph=bool(getattr(context, "repo_graph_ids", None)),
        has_reference_image=bool(getattr(context, "reference_image_url", None)),
        attachment_text_in_prompt=attachment_text_in_prompt,
        attachment_text_in_prompt_is_a_map=attachment_text_in_prompt_is_a_map,
        persona_labels=persona_labels,
    )
    decision = await decide_modes(
        user_input, prompt_input=prompt_input, model=model, execution=execution
    )
    if decision is None:
        return _unavailable_decision_plan(user_input, context, execution, explicit_files)
    canonical = canonical_route(decision.route)
    if canonical != decision.route:
        decision = replace(decision, route=canonical)
    execution.policy.set_flag("ordinary_conversation", _is_smalltalk(decision))

    events = [_decision_event(decision, {})]  # заменим ниже, когда план будет посчитан
    offered_mode: str | None = None
    route_hint = decision.route
    declined = execution.policy.flag("confirmation_declined")
    if (
        route_hint
        and not declined
        and not execution.policy.flag("document_tools_auto_approved")
        and _needs_confirmation(route_hint, decision.confidence, confirm_modes)
    ):
        events.append(_offer_event(decision, route_hint, user_input))
        offered_mode = route_hint
        route_hint = "general"

    plan = {
        "planning": planning if planning is not None else decision.needs_plan,
        "multi_intent": multi_intent if multi_intent is not None else decision.multi_step,
        "web_tool": decision.needs_fresh_data,
        "files_tool": decision.needs_files or explicit_files,
    }
    if decision.source == SOURCE_SHORTCUT:
        plan = {
            "planning": planning,
            "multi_intent": multi_intent,
            "web_tool": False,
            "files_tool": explicit_files,
        }

    already_agreed = bool(getattr(context, "video_tool_enabled", False))
    offered_tool: str | None = None
    if (
        offered_mode is None
        and not declined
        and not already_agreed
        and _mentions_a_video(user_input)
        and _video_offer_allowed()
    ):
        offered_tool = "watch_video"
        events.append(
            _tool_offer_event(
                offered_tool,
                "просмотр видео",
                "video_confirmation_required",
                user_input,
            )
        )

    events[0] = _decision_event(
        decision,
        plan,
        offered=route_hint != decision.route,
        reason_code=("confirmation_required" if offered_mode else None),
    )
    return AutoPlan(
        route_hint=route_hint,
        planning=plan["planning"],
        multi_intent=plan["multi_intent"],
        web_tool=bool(plan["web_tool"]),
        files_tool=bool(plan.get("files_tool")),
        force_decompose=(
            decision.source != SOURCE_SHORTCUT
            and multi_intent is None
            and bool(decision.multi_step)
        ),
        offered_mode=offered_mode,
        offered_tool=offered_tool,
        events=events,
    )
