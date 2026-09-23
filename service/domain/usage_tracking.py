"""Извлечение и агрегация usage-токенов из ответов провайдеров и Agents SDK.

Вынесено из base.py: чистые функции без зависимостей от агентов/стрима — единое
место разбора ``.usage``. chat/completions (``prompt_tokens``/``completion_tokens``)
и SDK ``ModelResponse`` (``input_tokens``/``output_tokens``) отличаются именами
полей, поэтому две функции извлечения, а не одна.
"""

from __future__ import annotations

from typing import Any

from service.domain.run_context import RunExecutionContext


def _extract_usage(response: Any) -> dict:
    """Достать токены из OpenAI-совместимого ответа (.usage). Пусто, если нет."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    if not prompt and not completion:
        return {}
    return {
        "prompt": prompt,
        "completion": completion,
        "total": int(getattr(usage, "total_tokens", 0) or (prompt + completion)),
    }


def _extract_sdk_run_usage(
    result: Any,
    *,
    execution: RunExecutionContext,
    model: str | None = None,
) -> dict:
    """Просуммировать токены по всем raw_responses прогона Agents SDK.

    ``Runner.run_streamed`` может сделать несколько LLM-вызовов за один прогон
    (tool-calling loop), поэтому usage суммируется по всем ``ModelResponse`` в
    ``result.raw_responses``. Поля SDK (``input_tokens``/``output_tokens``)
    отличаются от chat/completions (``prompt_tokens``/``completion_tokens``),
    поэтому отдельная функция, а не переиспользование ``_extract_usage``.
    """
    raw_responses = getattr(result, "raw_responses", None) or []
    prompt = completion = total = 0
    calls: list[dict[str, Any]] = []
    for index, resp in enumerate(raw_responses):
        usage = getattr(resp, "usage", None)
        if usage is None:
            continue
        call_prompt = int(getattr(usage, "input_tokens", 0) or 0)
        call_completion = int(getattr(usage, "output_tokens", 0) or 0)
        prompt += call_prompt
        completion += call_completion
        total += int(getattr(usage, "total_tokens", 0) or 0)
        call_model = str(getattr(resp, "model", None) or model or "") or None
        call_provider = str(getattr(resp, "provider", None) or "") or None
        receipt_id = f"sdk_{id(result):x}_{index}"
        from service.domain.usage_ledger import receipt_from_usage

        receipt = receipt_from_usage(
            {"prompt": call_prompt, "completion": call_completion},
            provider=call_provider,
            model=call_model,
            kind="chat",
            receipt_id=receipt_id,
        )
        execution.usage.record(receipt)
        calls.append(receipt.as_dict())
    if not prompt and not completion:
        return {}
    return {
        "prompt": prompt,
        "completion": completion,
        "total": total or (prompt + completion),
        "calls": calls,
    }


# --------------------------------------------------------------------------- #
# Накопление usage по ходу прогона (переехало из subagents/usage.py)           #
# --------------------------------------------------------------------------- #
# ⚠️ ПОЧЕМУ ПЕРЕЕХАЛО. Функции нужны не только субагентам: их зовут `pipeline/planning`,
# `pipeline/decomposition`, `routing/complexity`, `tools/router` и инструменты. Пока они
# жили в `subagents/`, импорт оттуда замыкал кольцо (`subagents/__init__` тянет ВСЕХ
# агентов, а те — половину домена), и четыре модуля обходили это ОТЛОЖЕННЫМ импортом
# внутри функции. Здесь зависимостей нет вовсе, поэтому импортировать можно нормально.


def is_billable(usage: dict | None) -> bool:
    """Есть ли в этом usage что тарифицировать.

    ⚠️ ЕДИНСТВЕННОЕ МЕСТО, ГДЕ ЭТО РЕШАЕТСЯ. Условие было продублировано в шести местах,
    и одна из копий (`/route`) проверяла ДРУГОЕ поле — `total` вместо `prompt`/
    `completion`. Два пути одного и того же вызова `route_model` расходились в
    противоположные стороны: провайдер, не заполнивший `total_tokens`, терял тарификацию
    роутинга на `/route` и сохранял на `/run`.

    Почему именно `prompt`/`completion`: цену считает backend
    (`pricing_service.price_request`) по этим двум полям ПО ОТДЕЛЬНОСТИ, для каждого своя
    ставка. `total` в цене не участвует нигде, поэтому usage без разбивки стоит РОВНО
    НОЛЬ — пропускать его дальше значит засорять `per_call_usage` записями по нулю.
    """
    if not isinstance(usage, dict):
        return False
    return bool(usage.get("prompt") or usage.get("completion"))


def build_token_usage_meta(usage: dict) -> dict | None:
    """``token_usage``-мета для AGENT_COMPLETE (базовый случай).

    Возвращает ``None``, если usage пуст (нечего тарифицировать) — вызывающий код
    может добавить свой фолбэк (напр. фикс-эквивалент за картинку).
    """
    if is_billable(usage):
        token_usage = {
            "prompt": usage.get("prompt", 0),
            "completion": usage.get("completion", 0),
            "total": usage.get("total", 0),
            "model": usage.get("model"),
        }
        for key in ("provider", "calls", "estimated"):
            if usage.get(key):
                token_usage[key] = usage[key]
        return {"token_usage": token_usage}
    return None
