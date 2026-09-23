"""Мульти-интент декомпозиция запроса (Фаза 2).

Дешёвый пре-фильтр по союзам отсекает одиночные интенты БЕЗ LLM-вызова (защита от
регресса латентности). Только при срабатывании фильтра делается один дешёвый
LLM-вызов, разбивающий сообщение на упорядоченные субтаски с категориями из
словарём маршрутов. Полностью fail-open: любая ошибка → None (одиночный маршрут).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from service.domain.capabilities import decomposable_names, render_decompose_categories
from service.domain.json_fence import strip_json_fence
from service.domain.llm_response import first_message_content
from service.domain.pipeline.planning import PLANNABLE_OVERRIDE
from service.domain.routing.policy import canonical_route
from service.domain.run_context import RunExecutionContext, require_execution
from service.settings import config
from service.shared import step_timing
from service.shared.agent_settings import runtime_settings

logger = logging.getLogger(__name__)

# Маркеры нескольких последовательных намерений в одном сообщении.
_MULTI_INTENT_RE = re.compile(
    r"(затем|потом|после\s+(?:этого|чего)|сначала|после\s+чего|;|\bthen\b|after\s+that|и\s+затем)",
    re.I,
)


# 🔴 Перечень категорий ГЕНЕРИРУЕТСЯ. Агент, забытый в прежнем литеральном списке,
# выпадал из мульти-интента молча: `_parse_subtasks` отсекал подзадачу с неизвестной
# категорией, и наружу это выглядело как «декомпозиция его просто не выбрала».
# `audio_transcribe` не попадает сюда сам — у него `decomposable=False`, потому что
# распознавание речи форсится типом вложения, а не текстом задачи.
def _decompose_prompt() -> str:
    return (
        "Ты разбиваешь запрос пользователя на упорядоченные подзадачи, если он содержит "
        "несколько последовательных намерений. Каждой подзадаче присвой категорию РОВНО из "
        f"набора: {render_decompose_categories()}. "
        "Если запрос одно-интентный — верни массив из ОДНОГО элемента. "
        'Для каждой подзадачи добавь "independent": true, ЕСЛИ она НЕ зависит от результата '
        "других подзадач (её можно выполнить параллельно); иначе false. Например «найди X и "
        "нарисуй Y» — обе independent; «найди X, ЗАТЕМ сделай по нему презентацию» — вторая "
        "зависит от первой (independent:false). "
        "Ответ — только JSON-массив без markdown: "
        '[{"category": "...", "instruction": "что сделать", "independent": true|false}].'
    )


@dataclass
class SubTask:
    category: str
    instruction: str
    independent: bool = False


def decomposition_allowed(
    *,
    multi_intent: bool | None,
    route_override: str | None,
    web_search: bool,
    deep_research: bool,
    input_type: str | None,
) -> bool:
    """Можно ли дробить запрос на подзадачи.

    Приоритет: явный per-user выбор (True/False) перекрывает глобальный admin/config-флаг;
    `None` (не прислан и оркестратор не решил) → глобальный дефолт.

    ⚠️ Применимо к ТЕКСТОВОМУ вводу. Фронт для текста шлёт `input_type='text'` (не None),
    поэтому проверяем на текст/пусто явно — был баг, где `not input_type` при
    `input_type='text'` давало False и душило декомпозицию у ВСЕХ текстовых сообщений.

    ⚠️ `general` — единственный форс, который декомпозицию НЕ запрещает: его ставит фронт
    при вложении документа, а не человек. Смысл и цена разбора — в
    `planning.PLANNABLE_OVERRIDE`; критерий один на оба гейта, чтобы «форс general» не
    начал значить разное в двух местах.
    """
    active = (
        multi_intent
        if multi_intent is not None
        else runtime_settings.get_agents("multi_intent_enabled", config.agents.multi_intent_enabled)
    )
    is_text_input = (not input_type) or input_type == "text"
    blocking_override = bool(route_override) and route_override != PLANNABLE_OVERRIDE
    return bool(
        active and not blocking_override and not web_search and not deep_research and is_text_input
    )


def looks_multi_intent(text: str) -> bool:
    """Дешёвый пре-фильтр: похоже ли на несколько последовательных намерений."""
    return bool(_MULTI_INTENT_RE.search(str(text or "")))


def _parse_subtasks(content: str) -> list[SubTask]:
    raw = strip_json_fence(content)
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[SubTask] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cat = canonical_route(str(item.get("category") or "").strip().lower()) or ""
        instr = str(item.get("instruction") or "").strip()
        if cat in set(decomposable_names()) and instr:
            out.append(
                SubTask(category=cat, instruction=instr, independent=bool(item.get("independent")))
            )
    return out


def _persona_decompose_prompt() -> str:
    """Промпт декомпозиции с надстройкой личности (без личности — без изменений)."""
    from service.domain import persona

    return persona.current().wrap(_decompose_prompt(), "decomposition")


@step_timing.measure("decompose")
async def decompose_intents(
    user_input: str,
    *,
    max_subtasks: int = 3,
    model: str | None = None,
    execution: RunExecutionContext | None = None,
    force: bool = False,
) -> list[SubTask] | None:
    """Вернуть >=2 субтаска для мульти-интент запроса, иначе None.

    None означает «обрабатывать как обычно одним маршрутом». ``model`` — выбранная
    пользователем модель; usage записывается непосредственно в run ledger.

    🔴 ``force`` обходит regex-пре-фильтр. Он ищет союзы («затем», «потом», «;»), а
    «найди статистику и нарисуй по ней график» их не содержит — то есть на самом частом
    виде составного запроса декомпозиция не запускалась НИКОГДА. Оркестратор видит
    контекст и решает лучше списка союзов; пре-фильтр остаётся для пути без него, где он
    бесплатно экономит вызов.
    """
    execution = require_execution(execution)
    if not force and not looks_multi_intent(user_input):
        return None
    try:
        from service.domain.client import (
            create_chat_completion,
            list_qualified_models,
        )
        from service.domain.model_runtime import invoke_model_call
        from service.domain.subagents.utils import pick_meta_model
        from service.domain.usage_ledger import UsageKind

        models = await list_qualified_models()
        model = pick_meta_model(models, model)
        if not model:
            return None
        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.META,
            execution=execution,
            messages=[
                {
                    "role": "system",
                    # КАК дробить составной запрос — часть специализации: аналитик отделит
                    # сбор данных от их интерпретации, таролог — считывание символов от
                    # толкования. Вызов ОДИН на запрос, поэтому цена не множится.
                    "content": _persona_decompose_prompt(),
                },
                {"role": "user", "content": str(user_input or "")},
            ],
            model=model,
            temperature=0.0,
            max_tokens=300,
        )
        resp = result.response
        content = first_message_content(resp)
        if not content:
            return None
        subtasks = _parse_subtasks(content)
        if len(subtasks) < 2:
            return None
        # ⚠️ Нижняя граница 2, а не `max_subtasks`: одна подзадача — это не мульти-интент,
        # и обрезка до неё лишила бы смысла сам режим. Но админ, поставивший
        # `max_subtasks=1`, получит ДВЕ — настройка в этом углу не действует.
        return subtasks[: max(2, int(max_subtasks))]
    except Exception:
        # ⚠️ УРОВЕНЬ WARNING, А НЕ DEBUG. `try` накрывает всё: импорты, список моделей,
        # сам LLM-вызов, разбор ответа. При типовом INFO-уровне логов постоянно
        # ломающаяся декомпозиция (протухший ключ, недоступный список моделей) не
        # оставляла НИ ОДНОЙ записи — а наружу это выглядит как «включил тумблер
        # мульти-интента, прислал „найди X, затем сделай Y“ и получил обычный ответ».
        # Жалоба ровно того же вида, что уже была: «кнопка не работает».
        logger.warning(
            "decomposition unavailable",
            extra={"failure_code": "unavailable"},
        )
        return None
