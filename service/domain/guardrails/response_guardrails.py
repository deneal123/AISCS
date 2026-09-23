from __future__ import annotations

import re

from agents import (
    Agent,
    GuardrailFunctionOutput,
    RunContextWrapper,
    input_guardrail,
    output_guardrail,
)

# Границы слов ОБЯЗАТЕЛЬНЫ: наивное `"мат" in text` срабатывало на «математика»,
# «формат», «информатика», «климат», «автомат» — любой безобидный запрос с таким
# словом ложно блокировался (аудит P0.4). `\b` в Python re для str юникод-осведомлён:
# `\bмат\b` ловит одиночное «мат», но не «математику». Остальные — по основе слова.
_ABUSIVE_RE = re.compile(r"\b(оскорблени\w*|ненавист\w*|угроз\w*|мат)\b", re.IGNORECASE)


@input_guardrail
async def check_appropriate_language(
    context: RunContextWrapper,
    agent: Agent,
    input,
) -> GuardrailFunctionOutput:
    """Block abusive language in user input."""
    try:
        input_text = " ".join(map(str, input)) if isinstance(input, (list, tuple)) else str(input)
    except Exception:
        input_text = ""

    found_words = _ABUSIVE_RE.findall(input_text)

    return GuardrailFunctionOutput(
        tripwire_triggered=bool(found_words),
        output_info={"found_words": found_words},
    )


@input_guardrail
async def check_forbidden_topics(
    context: RunContextWrapper,
    agent: Agent,
    input,
) -> GuardrailFunctionOutput:
    """Detect potentially unsafe request topics for escalation."""
    text = str(input or "").lower()
    forbidden = ["самоубий", "взрывчат", "вред себе", "как взломать"]
    found = [w for w in forbidden if w in text]
    return GuardrailFunctionOutput(
        tripwire_triggered=bool(found),
        output_info={"found": found},
    )


@output_guardrail
async def validate_response_relevance(
    context: RunContextWrapper,
    agent: Agent,
    output: str,
) -> GuardrailFunctionOutput:
    """Trip only on a runaway response length.

    Раньше верхняя отсечка была 8000 символов при chat_max_tokens=4096 (~16k+ симв.
    для кириллицы): нормальный длинный ответ ложно блокировался (аудит P0.4). Пустоту
    ловит ensure_non_empty_response, а короткие валидные ответы («42», «Да») больше не
    режем. Оставляем лишь защиту от откровенного разгона (обрезка и так делается выше).
    """
    length = len(output or "")
    runaway = length > 200_000
    return GuardrailFunctionOutput(
        tripwire_triggered=runaway,
        output_info={"length": length},
    )


@output_guardrail
async def ensure_non_empty_response(
    context: RunContextWrapper,
    agent: Agent,
    output: str,
) -> GuardrailFunctionOutput:
    """Trip if model returned an empty response."""
    empty = not str(output or "").strip()
    return GuardrailFunctionOutput(
        tripwire_triggered=empty,
        output_info={"empty": empty},
    )


@output_guardrail
async def fact_check_output(
    context: RunContextWrapper,
    agent: Agent,
    output: str,
) -> GuardrailFunctionOutput:
    """Advisory: пометить рискованные абсолютные формулировки, НЕ блокируя ответ.

    Раньше tripwire срабатывал на «гарантированно» / «100% безопасно» / «без рисков» и
    на SDK-пути ЦЕЛИКОМ блокировал ответ, где такое слово встречалось в безобидном
    контексте («это гарантированно работает») — грубый ложный блок (аудит P0.4). Это
    эвристический СИГНАЛ, а не запрет: найденное кладём в output_info (субагенты уже
    показывают его как аннотацию в metadata), но tripwire не поднимаем.
    """
    text = (output or "").lower()
    bad_phrases = ["гарантированно", "100% безопасно", "без рисков"]
    found = [p for p in bad_phrases if p in text]
    return GuardrailFunctionOutput(
        tripwire_triggered=False,
        output_info={"found": found},
    )
