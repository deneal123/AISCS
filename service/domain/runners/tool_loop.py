"""Раунды инструментов: исполнение, обрезка результатов и отчёт об отобранных.

Отделено от `chat_run` намеренно: там цикл стрима и финализация ответа, здесь — всё, что
относится к ВЫЗОВУ инструментов. Разные темы менялись по разным поводам и вместе перестали
помещаться в голову: функция стрима дважды упиралась в потолок храповика.

От хозяина примесь требует `name` и `tools` — состав держит `tests/test_agent_runner_mixins.py`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from service.domain.capabilities.tool_registry import (
    tool_billing_names,
    tool_concurrency_group,
    tool_dedup_safe,
    tool_result_limit,
)
from service.domain.runners.support import invoke_tool_outcome
from service.domain.runners.tool_execution import ToolCallCache, ToolCallOutcome, execute_tool_calls
from service.domain.runners.tool_runtime import ToolRoundEventProjector
from service.domain.tools import unbilled_calls
from service.domain.tools.result_compaction import compact_with_report
from service.events import AgentEvent, EventType

logger = logging.getLogger(__name__)


async def _invoke_tool(tool, ctx, arguments: str) -> ToolCallOutcome:
    """Patch seam for the typed invocation contract used by concurrent execution."""
    return await invoke_tool_outcome(tool, ctx, arguments)


# Одновременных вызовов инструментов в одном раунде. Не безлимит: модель может запросить
# сразу несколько тяжёлых (fetch_url, analyze_data), и пачка параллельных обращений к
# одному внешнему сервису упирается в его лимиты — выигрыш съедается ретраями.
_TOOL_CONCURRENCY = 4

# Результат инструмента переотправляется в КАЖДОМ следующем раунде tool-loop, поэтому
# большой ответ множится. 6000 символов ≈ 2-3k токенов — хватает на схему с превью данных
# или содержательную выжимку, но не на дамп таблицы целиком.
#
# ⚠️ Потолок берётся ИЗ СПЕКИ инструмента, а не один на всех: для канонического чтения
# (файл, документ) молча обрезанный результат — это НЕВЕРНЫЙ результат, а не короткий, и
# такому инструменту потолок снимают.
_TOOL_TRUNCATION_NOTE = (
    "\n\n[…результат инструмента усечён — покажи пользователю то, что есть, или "
    "уточни запрос к инструменту, чтобы вернуть меньше данных]"
)


def _trim_tool_result(result: str, tool_name: str) -> tuple[str, dict]:
    """Уложить результат инструмента в ЕГО потолок с наименьшей потерей.

    🔴 Раньше здесь была обрезка первых N символов — то есть выбрасывался КОНЕЦ, где у
    вывода команды, сборки или тестов и лежит смысл: код возврата, сообщение об ошибке,
    итог. Модель получала заголовок компиляции и ни строчки о том, чем всё кончилось.
    Теперь сначала схлопываются повторы (потерь нет вовсе), затем из середины спасаются
    значимые строки, и только потом сохраняются голова И хвост с маркером пропуска.

    Возвращает ТЕКСТ И ОТЧЁТ: незаметно урезанный результат неотличим от неполного ответа
    инструмента, поэтому «что применилось» обязано уехать наружу, а не остаться в модуле.
    """
    text = str(result or "")
    compacted, report = compact_with_report(text, tool_result_limit(tool_name))
    if report["lossy"]:
        compacted += _TOOL_TRUNCATION_NOTE
    return compacted, report


def _omissions_event(toolset, agent_name: str) -> AgentEvent | None:
    """Событие об инструментах, которые модель НЕ получила, — с причиной на каждый.

    🔴 Пустой список инструментов правдоподобен сам по себе, поэтому отказ, оставленный без
    имени, снаружи неотличим от «модель им не воспользовалась». Причина уезжает в трейс,
    чтобы «поиска не было» можно было увидеть, а не предполагать.
    """
    if not toolset.omissions:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={"kind": "tool_omissions", "omissions": toolset.as_meta()},
    )


def _tool_name(tool: Any) -> str:
    """Return a tool name without exposing its schema or arguments."""
    if isinstance(tool, dict):
        return str((tool.get("function") or {}).get("name") or "external_tool")
    return str(getattr(tool, "name", "") or "external_tool")


def tool_availability_event(toolset, agent_name: str) -> AgentEvent:
    """Describe the final tool set before the model can request a call.

    This is intentionally a status event, rather than an implementation detail in a
    log line: a missing confirmation and an unavailable capability require different
    next actions from the user.
    """
    offered = [_tool_name(tool) for tool in toolset.tools]
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={
            "kind": "tool_availability",
            "tool_availability": {
                "offered": offered,
                "omissions": toolset.as_meta(),
            },
        },
    )


def tool_summary_event(summary: dict[str, Any], agent_name: str) -> AgentEvent:
    """Emit a compact, argument-free summary of the tool portion of a run."""
    payload = dict(summary)
    payload["partial_success"] = bool(payload.get("succeeded") and payload.get("failed"))
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={"kind": "tool_summary", "tool_summary": payload},
    )


def _assistant_tool_message(tool_calls: list[dict], segment: str) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": segment or None,
        "tool_calls": [
            {
                "id": str(call.get("id") or f"call_invalid_{position}"),
                "type": "function",
                "function": {
                    "name": str(call.get("name") or "external_tool"),
                    "arguments": call.get("arguments") or "{}",
                },
            }
            for position, call in enumerate(tool_calls)
        ],
    }


def _append_tool_result(
    convo: list[dict], call: dict[str, Any], outcome: ToolCallOutcome
) -> tuple[str, dict[str, Any]]:
    result = outcome.text
    name = str(call.get("name") or "external_tool")
    trimmed, compaction = _trim_tool_result(result, name)
    convo.append(
        {
            "role": "tool",
            "tool_call_id": str(call.get("id") or "call_invalid"),
            "content": trimmed,
        }
    )
    return result, compaction


class ToolRoundMixin:
    """Исполнение раундов инструментов. Требования к хозяину — в докстринге модуля."""

    # Имя инструмента → имя для ТАРИФИКАЦИИ, отдельное от имени маршрута.
    # Имена надбавок берутся из спек инструментов: словарь здесь расходился бы с ними молча.

    @classmethod
    def _billable_tools_meta(cls, tool_name: str, billed: set[str]) -> dict | None:
        """Метаданные события с КУМУЛЯТИВНЫМ списком платных инструментов прогона.

        🔴 Список, а не одно значение: потребитель складывает метаданные ПЕРЕЗАПИСЬЮ, и
        одиночное затёрлось бы вторым вызовом. Надбавка берётся один раз за прогон —
        «два поиска = двойная плата» даёт жалобы «один вопрос стоил по-разному».

        ⚠️ Копилка приходит аргументом, а не живёт на хозяине: скрытый атрибут ловит страж
        примесей, и заодно накопитель не смешивает счета двух прогонов.
        """
        billing_name = tool_billing_names().get(tool_name)
        if not billing_name:
            return None
        # 🔴 ВЫЗОВ И РЕЗУЛЬТАТ — РАЗНОЕ. Инструмент, который сам сказал «услуга не
        # оказана» (поиск недоступен, ролик не скачался), надбавки не стоит: замерено
        # 833 кредита за поиск, у которого отвалились ВСЕ движки. Считаем вызовы против
        # отказов: один упавший вызов из трёх плату не отменяет.
        unbilled_calls.count_call(billing_name)
        if not unbilled_calls.billable(billing_name):
            return None
        billed.add(billing_name)
        return {"tool_name": tool_name, "billable_tools": sorted(billed)}

    async def _execute_tool_round(
        self,
        convo: list[dict],
        tool_calls: list[dict],
        tool_index: dict,
        tool_ctx: Any,
        segment: str,
        billed: set[str],
        *,
        round_number: int = 0,
        summary: dict[str, Any] | None = None,
        cache: ToolCallCache | None = None,
        dedup_mode: str = "enforce",
    ) -> AsyncGenerator[AgentEvent]:
        convo.append(_assistant_tool_message(tool_calls, segment))
        projector = ToolRoundEventProjector(self.name, round_number)
        yield projector.plan(tool_calls)
        for call in tool_calls:
            for event in projector.start(call):
                yield event
        results = await execute_tool_calls(
            tool_calls,
            tool_index,
            tool_ctx,
            concurrency=_TOOL_CONCURRENCY,
            invoker=_invoke_tool,
            cache=cache,
            dedup_safe=tool_dedup_safe,
            concurrency_group=tool_concurrency_group,
            dedup_mode=dedup_mode,
        )
        from service.domain.run_context import require_current_execution

        run_execution = require_current_execution()
        for call, outcome in zip(tool_calls, results, strict=True):
            run_execution.grounding.observe_outcome(
                str(call.get("name") or ""),
                outcome,
            )
            result, compaction = _append_tool_result(convo, call, outcome)
            name = str(call.get("name") or "external_tool")
            billing = self._billable_tools_meta(name, billed) if outcome.charged else None
            projector.update_summary(summary, outcome)
            for event in projector.completion(
                call,
                outcome,
                result_chars=len(result),
                compaction=compaction,
                billing_metadata=billing,
            ):
                yield event
