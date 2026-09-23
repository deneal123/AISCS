"""Стратегия `plan`: построение плана решения для сложных задач (План → синтез).

LLM строит короткий пошаговый план; план затем подмешивается в эффективный вход
general-агента, который отвечает по нему одним проходом. При сбое — деградация к
ответу без плана.
"""

from __future__ import annotations

import logging

from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.routing.complexity import assess_is_complex
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.utils import pick_meta_model
from service.domain.usage_ledger import UsageKind
from service.events import AgentEvent, EventType
from service.shared import step_timing

logger = logging.getLogger(__name__)

_MAX_TOKENS = 500

# 🔴 ЕДИНСТВЕННЫЙ ФОРС, КОТОРЫЙ НЕ ЗАПРЕЩАЕТ ПЛАН.
#
# `general` в `route_override` чаще всего ставит НЕ человек, а фронт: при вложении
# документа с извлечённым текстом он форсит general, чтобы категорийный роутер по словам
# «сводка/тренды/выводы» не увёл запрос в веб-поиск мимо самого файла
# (`useChatMessageSender.js`). Побочный эффект был такой: ЛЮБОЕ сообщение с приложенным
# PDF теряло и планирование, и декомпозицию, а человек, включивший планирование, читал в
# трейсе «выбран режим «general», а не Авто» — про режим, которого он не выбирал.
#
# Пункт «Обычный» в меню тоже приходит сюда, и это верно: он обещает ответ БЕЗ
# ИНСТРУМЕНТОВ, а не без плана. План инструментом не является — он подмешивается в тот же
# единственный вызов модели.
PLANNABLE_OVERRIDE = "general"


def plan_blockers(
    *,
    subtasks,
    multimodal: bool,
    agent_name: str,
    route_override: str | None,
    web_search: bool,
    deep_research: bool,
) -> str:
    """Что мешает построить план — ЧЕЛОВЕЧЕСКИМ текстом, а не булевым «нельзя».

    Раньше это был один длинный `and`, и при отказе наружу не уходило ничего. Человек
    включал планирование, не видел в трейсе ни строки и не мог отличить «флаг не доехал»
    от «маршрут не тот». Причина отказа — часть ответа на его действие.
    """
    reasons = []
    if subtasks:
        reasons.append("запрос разбит на подзадачи (мульти-интент)")
    if multimodal:
        reasons.append("параллельный разбор нескольких вложений")
    if route_override and route_override != PLANNABLE_OVERRIDE:
        reasons.append(f"выбран режим «{route_override}», а не Авто")
    if web_search:
        reasons.append("включён веб-поиск")
    if deep_research:
        reasons.append("включён глубокий поиск")
    if agent_name != "general" and not reasons:
        reasons.append(f"маршрут ушёл к «{agent_name}»")
    return "; ".join(reasons)


async def resolve_plan(
    user_input: str,
    *,
    planning: bool | None,
    model: str | None,
    execution: RunExecutionContext | None = None,
    blockers: str,
) -> tuple[str | None, list[AgentEvent]]:
    """Решить, строить ли план, и построить. → (plan_context, events).

    🔴 Отказ ОБЪЯСНЯЕТСЯ, если человек просил явно. Живая жалоба: «принудительно включил
    планирование, в трейсах не увидел ничего» — снаружи «флаг не доехал», «гейт отказал»
    и «план построен, но не показан» выглядели одинаково, а молчание на явную просьбу
    читается как «тумблер не работает».

    ⚠️ В режиме АВТО молчим: «не сложно» — штатное решение, а не отказ на просьбу.
    """
    logger.info("Планирование: запрошено=%s, помехи=%s", planning, blockers or "нет")
    if planning is False or blockers:
        if planning is True:
            return None, [
                AgentEvent(
                    type=EventType.STATUS_UPDATE,
                    agent_name="planner",
                    data=f"Планирование пропущено: {blockers}",
                    metadata={"kind": "plan_skipped", "blockers": blockers},
                )
            ]
        return None, []
    # ⚠️ ЯВНОЕ «ДА» ЭКОНОМИТ ВЫЗОВ. `assess_is_complex` — отдельное обращение к модели;
    # когда человек уже сказал «планируй», спрашивать «а сложно ли это» незачем.
    if planning is not True and not await assess_is_complex(
        user_input, model=model, execution=execution
    ):
        return None, []
    return await build_plan(user_input, model=model, execution=execution)


@step_timing.measure("plan")
async def build_plan(
    user_input: str,
    *,
    model: str | None = None,
    execution: RunExecutionContext | None = None,
) -> tuple[str, list[AgentEvent]]:
    """Построить план решения. Возвращает (plan_text, trace_events).

    ``model`` — выбранная пользователем модель; usage записывается в run ledger.
    """
    execution = require_execution(execution)
    events: list[AgentEvent] = [
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name="planner",
            data="Задача сложная — строю план решения",
            metadata={"strategy": "plan"},
        )
    ]

    try:
        from service.domain.client import (
            create_chat_completion,
            list_qualified_models,
        )

        models = await list_qualified_models()
        model = pick_meta_model(models, model)
        if not model:
            return "", events

        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.META,
            execution=execution,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты планировщик. Составь краткий пошаговый план решения задачи "
                        "(3–6 пунктов, по делу, без выполнения шагов). "
                        "Ответ — только нумерованный список."
                    ),
                },
                {"role": "user", "content": str(user_input or "")[:4000]},
            ],
            model=model,
            temperature=0.2,
            max_tokens=_MAX_TOKENS,
        )
        resp = result.response
        plan = first_message_content(resp).strip()
        if plan:
            steps = sum(1 for line in plan.splitlines() if line.strip())
            events.append(
                AgentEvent(
                    type=EventType.TOOL_CALL_COMPLETE,
                    agent_name="planner",
                    data=f"План готов: {steps} шаг(ов)",
                    # 🔴 САМ ПЛАН — В МЕТАДАННЫЕ. Раньше наружу уезжало только число
                    # шагов: план строился, подмешивался в промпт и влиял на ответ, а
                    # увидеть его было негде. Человек включил режим «Планирование» и не
                    # мог узнать, ни что было запланировано, ни выполнилось ли это —
                    # тумблер, чьё действие ненаблюдаемо, неотличим от выключенного.
                    #
                    # Потолок на всякий случай: план — вывод модели, а не наш текст, и
                    # неограниченная строка в каждом событии трейса нам не нужна.
                    metadata={"steps": steps, "plan": plan[:4000], "tool_name": "planner"},
                )
            )
        return plan, events
    except Exception:
        logger.warning("planning unavailable", extra={"failure_code": "unavailable"})
        return "", events
