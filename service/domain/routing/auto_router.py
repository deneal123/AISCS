"""Вызов авто-оркестратора: короткий путь → модель → нормализация → `None`.

🔴 ТРАНСПОРТ — `chat/completions`, А НЕ SDK `output_type`. Категорийный роутер ходит через
SDK-Responses, и ровно поэтому в нём живёт отдельная ветка для одного провайдера: у части
провайдеров этот путь ненадёжен. `create_chat_completion` работает у всех одинаково —
тем же способом уже собраны декомпозиция и оценка сложности.

Побочно обходится дефект соседа: `create_router_agent` не передаёт `model=`, и категорийный
роутер уходит на дефолтную модель SDK — выбор пользователя на него не влияет вовсе. Здесь
модель берётся через `pick_meta_model`, то есть служебный вызов согласован с моделью
диалога и тарифицируется по её цене.

Fail-open целиком: `None` означает буквально «работай как раньше» — старый роутер и есть
фолбэк нового, отдельного аварийного пути писать не нужно.
"""

from __future__ import annotations

import logging
from typing import Any

from service.domain.llm_response import first_message_content
from service.domain.routing.auto_decision import AutoDecision, normalize_decision
from service.domain.routing.auto_prompt import auto_prompt
from service.domain.routing.auto_signals import shortcut_decision
from service.domain.run_context import RunExecutionContext
from service.shared import step_timing

logger = logging.getLogger(__name__)

# `reason` больше не генерируется моделью: trace объясняется bounded policy-кодом.
# У компактного пятифлагового JSON прежнего лимита достаточно.
_MAX_TOKENS = 120


def _parse_json(raw: str) -> Any:
    """JSON из ответа модели — тем же способом, что декомпозиция: модели упорно
    заворачивают ответ в ```-ограду, несмотря на прямой запрет в промпте."""
    import json

    from service.domain.json_fence import strip_json_fence

    try:
        return json.loads(strip_json_fence(str(raw or "")))
    except Exception:  # noqa: BLE001 — разбор чужого текста, падать здесь нельзя
        return None


@step_timing.measure("auto_decide")
async def decide_modes(
    user_input: str,
    *,
    prompt_input: str,
    model: str | None = None,
    execution: RunExecutionContext | None = None,
) -> AutoDecision | None:
    """Решение оркестратора. `None` — «не смогли, поведение прежнее».

    `user_input` идёт в бесплатный короткий путь, `prompt_input` — собранный контекст для
    модели. Два аргумента, потому что короткий путь смотрит ТОЛЬКО на текущее сообщение:
    подмешай туда историю — и «а теперь найди свежее» после долгой беседы начнёт
    короткозамыкаться в обычный ответ.
    """
    if shortcut := shortcut_decision(user_input):
        logger.info("Авто: %s (без вызова модели)", shortcut.reason_code)
        return shortcut

    try:
        from service.domain.client import create_chat_completion, list_qualified_models
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
                {"role": "system", "content": auto_prompt()},
                {"role": "user", "content": prompt_input},
            ],
            model=model,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
        )
        resp = result.response
        decision = normalize_decision(_parse_json(first_message_content(resp)))
    except Exception:
        logger.warning("auto router unavailable", extra={"failure_code": "unavailable"})
        return None

    if decision is None:
        logger.warning("Авто-оркестратор вернул неразбираемый ответ — поведение прежнее")
    else:
        logger.info(
            "Авто: route=%s conf=%s fresh=%s plan=%s multi=%s code=%s",
            decision.route,
            decision.confidence,
            decision.needs_fresh_data,
            decision.needs_plan,
            decision.multi_step,
            decision.reason_code,
        )
    return decision
