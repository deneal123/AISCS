"""Исполнение мульти-интент плана и ре-роут при сбое (Фаза 2).

run_with_reroute — одиночный маршрут с однократным ре-роутом на general при
ошибке ДО выдачи контента (прозрачный passthrough на успехе). execute_steps —
последовательное исполнение субтасков с прокидыванием выводов в контекст и
финальным синтезом одним general-ответом (стримится только синтез).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from service.domain.runners.support import max_tokens_override
from service.events import AgentEvent, EventType
from service.shared.token_budget import chars_for_tokens

logger = logging.getLogger(__name__)

_TRACE_TYPES = {EventType.TOOL_CALL_START, EventType.TOOL_CALL_COMPLETE, EventType.STATUS_UPDATE}

# Ключи метаданных, несущие сгенерированный артефакт под-шага (картинка/презентация).
# Под мультиинтентом их надо ПРОБРОСИТЬ наверх (см. execute_steps), иначе файл теряется,
# хотя генерация уже оплачена.
_ARTIFACT_META_KEYS = (
    "b64_json",
    "pptx_b64",
    "filename",
    "file_url",
    "generated_files",
    "document_artifacts",
)


async def run_with_reroute(
    *,
    orchestrator,
    agent_name: str,
    user_input: str,
    context: Any,
    reroute_enabled: bool = True,
) -> AsyncGenerator[AgentEvent]:
    """Прогнать выбранный агент; при ERROR без контента — один ре-роут на general.

    Ре-роут возможен только пока не отдан НИ ОДИН контент-чанк (иначе пользователь
    уже видит часть ответа). На happy-path — прозрачный проброс событий.
    """
    agent = orchestrator.get_agent(agent_name)
    had_content = False
    async for event in agent.process(user_input, context):
        if event.type == EventType.STREAM_CHUNK and event.data:
            had_content = True
        # guardrail_block — это НЕ сбой агента, а осознанная блокировка небезопасного
        # входа. Ре-роут на general (у которого свой вход-гейт) её бы обошёл, отдав
        # тот же запрос заново → блок становился no-op (аудит P0.4). Такие ERROR
        # прокидываем как есть, без ре-роута.
        is_guardrail_block = (event.metadata or {}).get("failure_code") == "policy"
        if (
            event.type == EventType.ERROR
            and not had_content
            and not is_guardrail_block
            and reroute_enabled
            and bool(getattr(agent, "allow_failure_reroute", True))
            and agent_name != "general"
        ):
            logger.info("agent rerouted after failure", extra={"reason_code": "fallback"})
            general = orchestrator.get_agent("general")
            async for gevent in general.process(user_input, context):
                yield gevent
            return
        yield event


# Потолок «контекста предыдущих шагов»: augment дописывается к system_context,
# который УЖЕ собран под бюджет окна модели. Без потолка N многотысячных шагов
# переполнили бы окно (провайдер 400 / молчаливая обрезка самой задачи) — аудит B6.
_MAX_PRIOR_TOKENS = 4000


def _augment_context(context: Any, accumulated: list[tuple[str, str]]) -> Any:
    """Добавить выводы предыдущих шагов в system_context (не мутируя оригинал).

    Блок предыдущих шагов КЛАМПИТСЯ по токенам: system_context уже собран под бюджет
    окна, и неограниченный augment его переполнял. При переполнении держим ХВОСТ —
    ближайшие шаги важнее для «шаг N видит N-1».
    """
    if not accumulated:
        return context
    blocks = [f"### Результат шага ({cat})\n{txt}".strip() for cat, txt in accumulated if txt]
    if not blocks:
        return context
    body = "\n\n".join(blocks)
    cap = chars_for_tokens(_MAX_PRIOR_TOKENS)
    if len(body) > cap:
        body = "…[ранние шаги обрезаны]\n" + body[-cap:]
    prior = "## Контекст предыдущих шагов\n" + body
    base = getattr(context, "system_context", None) or ""
    merged = f"{base}\n\n{prior}".strip() if base else prior
    try:
        return context.model_copy(update={"system_context": merged})
    except Exception:
        # ⚠️ Самый тихий отказ мульти-интента: шаг N не видит вывод шагов 1..N-1 — ровно
        # то, ради чего последовательная ветка и существует. Снаружи всё зелёное, а ответ
        # собран как «сделай презентацию по найденному» без найденного. Раньше стоял
        # голый `return context` без лога.
        logger.warning(
            "execution context unavailable",
            extra={"failure_code": "unavailable"},
        )
        return context


def _build_synthesis_prompt(user_input: str, accumulated: list[tuple[str, str]]) -> str:
    parts = [
        f"Запрос пользователя:\n{user_input}",
        "\nНиже результаты выполненных шагов. Собери из них единый связный ответ "
        "пользователю на русском, без упоминания внутренних шагов.\n",
    ]
    for idx, (cat, txt) in enumerate(accumulated):
        parts.append(f"### Шаг {idx + 1} ({cat})\n{txt}")
    return "\n\n".join(parts)


async def _run_one_step(agent, category: str, instruction: str, context: Any) -> dict[str, Any]:
    """Прогнать под-агент до конца, СОБРАВ (не йелдя) результат и события к ре-эмиту.

    Возвращает {text, step_failed, error_message, reemit}. reemit — события к выдаче
    наверх (usage/артефакт/ошибка):
    - token_usage под-агент вешает на своё AGENT_COMPLETE — ре-эмитим отдельным
      STATUS_UPDATE, иначе billing видит только синтез (недобилл = число подзадач);
    - артефакт (b64_json/pptx_b64) висит в metadata STREAM_CHUNK — ре-эмитим, иначе
      пользователь платит за генерацию, но файла не получает.
    Собираем в ЦЕЛЬНЫЙ бандл, чтобы параллельные шаги не интерливили частичные
    события друг друга; контент шага (STREAM_CHUNK) наружу не течёт — стримит синтез.
    """
    text = ""
    step_failed = False
    error_message = ""
    reemit: list[AgentEvent] = []
    async for event in agent.process(instruction, context):
        usage = event.metadata.get("token_usage") if event.metadata else None
        if usage and event.type != EventType.ERROR:
            reemit.append(
                AgentEvent(
                    type=EventType.STATUS_UPDATE,
                    agent_name=category,
                    data="",
                    metadata={"token_usage": usage, "kind": "multi_intent_usage"},
                )
            )
        if event.metadata:
            artifact_meta = {k: v for k, v in event.metadata.items() if k in _ARTIFACT_META_KEYS}
            if artifact_meta:
                # СПИСКОМ, а не singular-ключами: два шага одной модальности (2×image_gen)
                # затёрли бы друг друга по ключу b64_json при слиянии metadata — юзер
                # платил бы за N генераций, получая 1 (аудит A4).
                reemit.append(
                    AgentEvent(
                        type=EventType.STATUS_UPDATE,
                        agent_name=category,
                        data="",
                        metadata={
                            "multi_intent_artifacts": [artifact_meta],
                            "kind": "multi_intent_artifact",
                        },
                    )
                )
        if event.type == EventType.STREAM_CHUNK and event.data:
            text += str(event.data)
        elif event.type == EventType.STRUCTURED_OUTPUT and event.data is not None:
            # Свернуть в текст для синтеза, иначе шаг без обычных чанков даёт пустой
            # результат → «[Шаг не выполнен]». ⚠️ Сегодня этот тип не эмитит НИКТО, но
            # он объявлен в контракте событий (сверяется парити-гейтом): молча терять
            # его при появлении нового агента хуже, чем держать четыре строки про запас.
            text += (
                event.data
                if isinstance(event.data, str)
                else json.dumps(event.data, ensure_ascii=False)
            )
        elif event.type == EventType.ERROR:
            step_failed = True
            error_message = str(event.data or "")
            reemit.append(event)  # не глотаем ошибку шага — прокидываем в трейс/клиенту
        elif event.type in _TRACE_TYPES:
            continue  # промежуточные трейс-события шага не плодим — прогресс в баре
    return {
        "text": text,
        "step_failed": step_failed,
        "error_message": error_message,
        "reemit": reemit,
    }


def _step_result_text(res: dict) -> str:
    if res["step_failed"] and not res["text"].strip():
        return f"[Шаг не выполнен: {res['error_message'] or 'ошибка агента'}]"
    return res["text"]


async def execute_steps(
    *,
    orchestrator,
    subtasks: list,
    context: Any,
    user_input: str,
    synthesis_max_tokens: int = 1200,
) -> AsyncGenerator[AgentEvent]:
    """Исполнить субтаски и стримить финальный синтез general-агента.

    Независимые шаги (декомпозиция пометила ``independent``) гоняются ПАРАЛЛЕЛЬНО —
    иначе N× латентность там, где шаги друг от друга не зависят. Если есть хоть один
    зависимый шаг — последовательно (шаг N видит вывод N-1 через _augment_context).
    """
    accumulated: list[tuple[str, str]] = []
    total = len(subtasks)
    # Прогресс-бар (как в deep research): единый бар через kind=multi_intent_progress
    # + progress (0..100) + label, а не россыпь строк-статусов. Фронт роутит эти
    # события в updateTraceProgress вместо appendTraceEvent.
    yield AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name="planner",
        data=f"Разбил запрос на шаги: {total}",
        metadata={
            "kind": "multi_intent_progress",
            "progress": 0,
            "label": f"Мульти-интент: {total} подзадач(и)",
            "steps": [getattr(s, "category", "general") for s in subtasks],
        },
    )

    all_independent = total >= 2 and all(getattr(s, "independent", False) for s in subtasks)

    if all_independent:
        # ПАРАЛЛЕЛЬНЫЙ путь: все шаги независимы → один базовый контекст (без augment),
        # эмитим бандл каждого по мере готовности (as_completed), accumulated собираем
        # в ИСХОДНОМ порядке для синтеза.
        async def _run(idx: int, st) -> tuple[int, str, dict]:
            cat = getattr(st, "category", "general")
            instr = getattr(st, "instruction", user_input)
            return idx, cat, await _run_one_step(orchestrator.get_agent(cat), cat, instr, context)

        tasks = [asyncio.ensure_future(_run(idx, st)) for idx, st in enumerate(subtasks)]
        results: dict[int, tuple[str, dict]] = {}
        done = 0
        try:
            for fut in asyncio.as_completed(tasks):
                idx, cat, res = await fut
                for ev in res["reemit"]:
                    yield ev
                results[idx] = (cat, res)
                done += 1
                yield AgentEvent(
                    type=EventType.STATUS_UPDATE,
                    agent_name=cat,
                    data=f"Готово {done}/{total}",
                    metadata={
                        "kind": "multi_intent_progress",
                        "progress": round(done / total * 100),
                        "label": f"Готово {done}/{total} (параллельно)",
                        "chars": len(res["text"]),
                        "failed": res["step_failed"],
                    },
                )
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        for idx in range(total):
            cat, res = results[idx]
            accumulated.append((cat, _step_result_text(res)))
    else:
        # ПОСЛЕДОВАТЕЛЬНЫЙ путь (дефолт): шаг N видит вывод предыдущих.
        for idx, st in enumerate(subtasks):
            category = getattr(st, "category", "general")
            instruction = getattr(st, "instruction", user_input)
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=category,
                data=f"Шаг {idx + 1}/{total}: {category}",
                metadata={
                    "kind": "multi_intent_progress",
                    "progress": round(idx / total * 100),
                    "label": f"Шаг {idx + 1}/{total}: {category}",
                },
            )
            step_context = _augment_context(context, accumulated)
            res = await _run_one_step(
                orchestrator.get_agent(category), category, instruction, step_context
            )
            for ev in res["reemit"]:
                yield ev
            accumulated.append((category, _step_result_text(res)))
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=category,
                data=(
                    f"Шаг {idx + 1} завершился с ошибкой"
                    if res["step_failed"]
                    else f"Шаг {idx + 1} готов"
                ),
                metadata={
                    "kind": "multi_intent_progress",
                    "progress": round((idx + 1) / total * 100),
                    "label": (
                        f"Шаг {idx + 1}/{total}: ошибка"
                        if res["step_failed"]
                        else f"Шаг {idx + 1}/{total} готов"
                    ),
                    "chars": len(res["text"]),
                    "failed": res["step_failed"],
                },
            )

    # Финальный синтез — единственный шаг, который стримит контент пользователю. Контекст
    # НЕ аугментируем: результаты шагов уже целиком в synthesis_prompt, а вторая вставка
    # через system_context переполняла собранный под бюджет окна запрос (аудит B6).
    general = orchestrator.get_agent("general")
    synthesis_prompt = _build_synthesis_prompt(user_input, accumulated)
    # ⚠️ Работает только ВНИЗ: поднять общий `chat_max_tokens` отсюда нельзя. Раньше
    # `synthesis_max_tokens` приезжал из настроек обоих сервисов и не читался ни разу.
    with max_tokens_override(synthesis_max_tokens):
        async for event in general.process(synthesis_prompt, context):
            yield event
