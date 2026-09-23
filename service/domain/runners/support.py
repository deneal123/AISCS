"""Общие помощники обоих путей исполнения агента.

Живут отдельно от `base.py`, потому что нужны И ему, И обеим примесям
(`sdk_run.py`, `chat_run.py`). Держать их в `base.py` было бы кольцом импортов:
`base` тянет примеси, примеси тянули бы `base`.

Код перенесён ПОБУКВЕННО. ⚠️ Первая попытка написать `_resolve_chat_max_tokens`
заново дала ТИХУЮ регрессию: моя версия читала только конфиг, а настоящая читает
runtime-оверлей админки поверх него. Тумблер «максимум токенов ответа» перестал бы
действовать, не сломав ничего заметного.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from service.domain.capabilities.tool_registry import tool_timeout
from service.domain.integration_failure import IntegrationFailure, IntegrationFailureCode
from service.domain.runners.tool_execution import ToolCallOutcome
from service.domain.runners.tool_runtime.contracts import ToolFailureCode
from service.shared import deadline

logger = logging.getLogger(__name__)

# Разовый потолок токенов для КОНКРЕТНОГО вызова агента.
#
# ⚠️ ЧЕРЕЗ ContextVar, А НЕ ПАРАМЕТРОМ. Потолок нужен вызывающему, который зовёт агента
# через общий `agent.process(...)` — синтезу мульти-интента. Протащить его параметром
# значило бы менять сигнатуру `process` у ВСЕХ субагентов ради одного случая. ContextVar
# в asyncio живёт в пределах задачи, а каждый запрос — своя задача, так что на соседние
# запросы значение не протекает. Тот же приём уже применён в `step_timing` и
# `provider_policy`.
_MAX_TOKENS_OVERRIDE: ContextVar[int | None] = ContextVar(
    "gpthub_max_tokens_override", default=None
)


@contextmanager
def max_tokens_override(limit: int | None):
    """Ограничить ответ агента на время блока. ``None``/0 — без ограничения."""
    if not limit or limit <= 0:
        yield
        return
    token = _MAX_TOKENS_OVERRIDE.set(int(limit))
    try:
        yield
    finally:
        _MAX_TOKENS_OVERRIDE.reset(token)


_CONTINUE_NUDGE = (
    "Продолжи предыдущий ответ ровно с того места, где он оборвался. Не повторяй "
    "уже написанное, без приветствий и вступлений — просто бесшовно продолжи текст."
)


def _as_int(value: Any, default: int) -> int:
    """Безопасно привести настройку к неотрицательному int (оверлей из БД может
    прийти строкой). При мусоре — вернуть default."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n >= 0 else default


def _tools_to_openai(tools) -> list[dict]:
    """FunctionTool (Agents SDK) → описания инструментов для chat/completions.

    SDK умеет это сам, но только на своём пути — а он обойдён для всех наших
    провайдеров ради реалтайм-стрима. Сериализуем сами, схема уже приведена к
    strict-виду в `FunctionTool.__post_init__`.
    """
    out: list[dict] = []
    for tool in tools or []:
        name = getattr(tool, "name", None)
        schema = getattr(tool, "params_json_schema", None)
        if not name or not isinstance(schema, dict):
            continue
        out.append(
            {
                "type": "function",
                # Internal compilation hint. It is consumed by provider protocol and
                # never reaches a provider payload.
                "dynamic": bool(getattr(tool, "source", "") == "mcp"),
                "function": {
                    "name": name,
                    "description": getattr(tool, "description", "") or "",
                    "parameters": schema,
                },
            }
        )
    return out


async def invoke_tool_outcome(tool, ctx, arguments: str) -> ToolCallOutcome:
    """Invoke once and retain a typed outcome for the tool loop's accounting."""
    """Исполнить инструмент. Ошибку возвращаем МОДЕЛИ текстом, а не роняем ход:
    модель сможет объясниться или попробовать иначе.

    🔴 Таймаут КЛАМПИТСЯ остатком бюджета прогона. Свои таймауты у инструментов щедрые
    (сайдкар DuckDB бюджетирует 60 с, `fetch_url` — 20 с на попытку), и у дедлайна прогона
    они ничего не спрашивали: один медленный вызов съедал время, нужное чтобы вообще
    сформулировать ответ, и человек получал обрыв вместо частичного результата.
    """
    name = str(getattr(tool, "name", "?"))
    budget = deadline.clamp(tool_timeout(name))
    from service.domain.run_context import tool_context_payload

    source_context = getattr(ctx, "context", ctx)
    narrowed_payload = tool_context_payload(source_context, name)
    try:
        narrowed_context = type(ctx)(narrowed_payload)
    except Exception:  # noqa: BLE001
        from types import SimpleNamespace

        narrowed_context = SimpleNamespace(context=narrowed_payload)
    try:
        result = await asyncio.wait_for(
            tool.on_invoke_tool(narrowed_context, arguments or "{}"), timeout=budget
        )
    except TimeoutError:
        logger.warning("Tool '%s' не уложился в %.0f с (бюджет прогона)", name, budget)
        return ToolCallOutcome(
            f"Инструмент «{name}» не успел ответить за {budget:.0f} с. "
            "Ответь тем, что уже есть, и скажи об этом прямо.",
            "failed",
            0.0,
            retryable=True,
            billable=False,
            failure_code=ToolFailureCode.TIMEOUT,
        )
    except IntegrationFailure as exc:
        failure = {
            IntegrationFailureCode.TIMEOUT: ToolFailureCode.TIMEOUT,
            IntegrationFailureCode.TRANSPORT: ToolFailureCode.TRANSPORT,
            IntegrationFailureCode.REMOTE: ToolFailureCode.REMOTE,
            IntegrationFailureCode.PROTOCOL: ToolFailureCode.PROTOCOL,
            IntegrationFailureCode.CONFLICT: ToolFailureCode.CONFLICT,
            IntegrationFailureCode.EXPIRED: ToolFailureCode.UNAVAILABLE,
            IntegrationFailureCode.UNAVAILABLE: ToolFailureCode.UNAVAILABLE,
            IntegrationFailureCode.INVALID: ToolFailureCode.INVALID_ARGUMENTS,
            IntegrationFailureCode.CANCELLED: ToolFailureCode.CANCELLED,
            IntegrationFailureCode.POLICY: ToolFailureCode.POLICY,
            IntegrationFailureCode.INTERNAL: ToolFailureCode.INTERNAL,
        }[exc.code]
        logger.warning("Tool '%s' failed with bounded code '%s'", name, failure.value)
        return ToolCallOutcome(
            exc.model_message(),
            "failed",
            0.0,
            retryable=exc.retryable,
            billable=False,
            failure_code=failure,
        )
    except Exception:  # noqa: BLE001
        failure = ToolFailureCode.INTERNAL
        logger.warning("Tool '%s' failed with bounded code '%s'", name, failure.value)
        return ToolCallOutcome(
            "Инструмент завершился безопасно обработанной ошибкой. "
            "Продолжи без результата или исправь вызов, если это возможно.",
            "failed",
            0.0,
            retryable=False,
            billable=False,
            failure_code=failure,
        )
    if isinstance(result, ToolCallOutcome):
        return result
    if isinstance(result, str):
        return ToolCallOutcome(result, "succeeded", 0.0)
    try:
        text = json.dumps(result, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        text = str(result)
    return ToolCallOutcome(text, "succeeded", 0.0)


async def _invoke_tool(tool, ctx, arguments: str) -> str:
    """Compatibility wrapper for direct callers that need only the model-facing text."""
    return (await invoke_tool_outcome(tool, ctx, arguments)).text


def _resolve_chat_max_tokens() -> int:
    """Потолок токенов ответа чата: runtime-оверлей (админка) поверх конфига.
    Был захардкожен 900 → длинные ответы обрезались.

    ⚠️ Разовый потолок конкретного вызова (см. :func:`max_tokens_override`) ПЕРЕБИВАЕТ
    общий — но только вниз. Поднять потолок выше настроенного отсюда нельзя: иначе
    отдельный шаг конвейера смог бы обойти лимит, выставленный админом на весь чат.
    """
    from service.settings import config as _config
    from service.shared.agent_settings import runtime_settings

    general = _as_int(
        runtime_settings.get_agents("chat_max_tokens", _config.agents.chat_max_tokens), 4096
    )
    override = _MAX_TOKENS_OVERRIDE.get()
    return min(general, override) if override else general
