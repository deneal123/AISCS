"""Оценка сложности задачи для выбора стратегии оркестратора.

Гибрид: дешёвые эвристики отсеивают явно простые/сложные случаи без LLM, а в
спорных случаях задаётся один короткий LLM-вопрос. Любой сбой деградирует к
эвристике, чтобы не ломать основной поток.
"""

from __future__ import annotations

import logging
import re

from service.domain.llm_response import first_message_content
from service.domain.run_context import RunExecutionContext, require_execution
from service.shared import step_timing

logger = logging.getLogger(__name__)

_COMPLEX_MARKERS = re.compile(
    r"(сравни|сравнен|проанализир|разработай\s+план|поэтапн|пошагов|стратег|архитектур|"
    r"спроектир|обоснуй|всесторонн|детальн|план\s+действий|декомпоз|"
    r"compare|step[\s-]?by[\s-]?step|trade[\s-]?off|pros and cons|design a|analyze|breakdown)",
    re.I,
)
_SIMPLE_WORD_LIMIT = 12
_LONG_WORD_LIMIT = 60


def _word_count(text: str) -> int:
    return len(str(text or "").split())


def has_complex_markers(text: str) -> bool:
    return bool(_COMPLEX_MARKERS.search(str(text or "")))


@step_timing.measure("complexity")
async def assess_is_complex(
    user_input: str,
    *,
    model: str | None = None,
    execution: RunExecutionContext | None = None,
) -> bool:
    """Нужна ли стратегия планирования (декомпозиция) для запроса.

    ``model`` — выбранная пользователем модель; usage записывается в run ledger.
    """
    execution = require_execution(execution)
    text = str(user_input or "").strip()
    words = _word_count(text)
    markers = has_complex_markers(text)

    # Короткий запрос без маркеров — однозначно простой (без LLM).
    if words <= _SIMPLE_WORD_LIMIT and not markers:
        return False
    # Ни маркеров, ни существенной длины — простой (без LLM).
    if not markers and words < _LONG_WORD_LIMIT:
        return False

    # Спорный случай — уточняем у LLM.
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
            return markers

        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.META,
            execution=execution,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты классификатор сложности задачи. Ответь строго JSON "
                        '{"complexity":"simple|complex"}. complex — если задача требует '
                        "многошагового рассуждения, декомпозиции, сравнения вариантов или плана; "
                        "simple — короткий фактический или прямой запрос."
                    ),
                },
                {"role": "user", "content": text[:2000]},
            ],
            model=model,
            temperature=0.0,
            max_tokens=20,
        )
        resp = result.response
        reply = first_message_content(resp)
        return "complex" in reply.lower()
    except Exception:
        logger.debug("complexity assessor unavailable", extra={"failure_code": "unavailable"})
        return markers
