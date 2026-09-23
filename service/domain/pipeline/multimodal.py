"""Мультимодальный fan-out: параллельный анализ модальностей и агрегация.

При нескольких модальностях контекста запускаем специализированных
субагентов-аналитиков параллельно, затем собираем их выводы в один размеченный
контекст для финального ответа general-агента.
"""

from __future__ import annotations

import asyncio
import logging

from service.domain.media import frame_description
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.modality_analysts import get_modality_analyst
from service.domain.usage_ledger import UsageKind
from service.events import AgentEvent, EventType
from service.schemas.agents import ModalityAttachment
from service.shared import step_timing
from service.shared.token_budget import trim_text_to_tokens

logger = logging.getLogger(__name__)

_KIND_TITLES = {
    "image": "Изображение",
    "audio": "Аудио",
    "data": "Данные",
    "code": "Код",
    "document": "Документ",
    "other": "Вложение",
}

# Маршруты-генераторы не потребляют контекст модальностей как текст, поэтому
# fan-out для них пропускаем.
_GENERATION_ROUTES = {"image_gen", "pdf_gen"}

# Сколько сырого текста отдаём в контекст, если аналитик не отработал. Тот же порядок,
# что и у фолбэка внутри самого аналитика: без потолка дамп многостраничного файла
# вытеснил бы из окна остальные вложения.
_RAW_FALLBACK_TOKENS = 2000


def normalize_attachments(raw) -> list[ModalityAttachment]:
    """Привести входные вложения к списку непустых ModalityAttachment.

    Потолок числа вложений — здесь, а не только на фронте: каждое вложение это отдельный
    LLM-вызов в fan-out, и клиент, приславший сотню, устроил бы себе (и нам) веер запросов.
    """
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    limit = int(
        runtime_settings.get_agents(
            "max_attachments_per_message", config.agents.max_attachments_per_message
        )
        or 8
    )
    result: list[ModalityAttachment] = []
    for item in raw or []:
        if isinstance(item, ModalityAttachment):
            att = item
        elif isinstance(item, dict):
            try:
                att = ModalityAttachment(**item)
            except Exception:
                logger.debug("malformed attachment skipped", extra={"failure_code": "invalid"})
                continue
        else:
            continue
        if str(att.content or "").strip():
            result.append(att)
        if len(result) >= limit:
            logger.info("вложений больше лимита (%s) — лишние отброшены", limit)
            break
    return result


def should_fan_out(
    attachments: list[ModalityAttachment], route_override: str | None = None
) -> bool:
    """Fan-out нужен при >=2 модальностях и не для маршрутов-генераторов."""
    if route_override in _GENERATION_ROUTES:
        return False
    return len(attachments) >= 2


def build_multimodal_route_events(count: int) -> tuple[AgentEvent, AgentEvent]:
    """Routing-события для мультимодальной ветки (финальный агент — general)."""
    routing_start = AgentEvent(
        type=EventType.ROUTING_START,
        data="Несколько модальностей — запускаю параллельный анализ...",
    )
    routing_complete = AgentEvent(
        type=EventType.ROUTING_COMPLETE,
        agent_name="general",
        data="Выбран агент: general (мультимодальная агрегация)",
        metadata={"agent_type": "general", "multimodal": True, "modalities_count": count},
    )
    return routing_start, routing_complete


_RELOOK_MAX_BYTES = 8 * 1024 * 1024


async def _content_for_persona(
    att: ModalityAttachment, execution: RunExecutionContext | dict | None
) -> str:
    """Материал для аналитика: при необходимости — ПЕРЕСМОТРЕННЫЙ под личность.

    Описание картинки делается на АПЛОАДЕ, когда личность ещё не выбрана (её выбирают на
    сообщении и могут сменить между сообщениями). Обычно этого хватает: базовый промпт
    зрения требует счёт объектов и дословный текст, и аналитик вытянет из него нужное.
    Но там, где угол зрения меняет не акценты, а сам предмет наблюдения (таролог читает
    расклад, инженер — схему), описание общего назначения помочь уже не может.

    ТРИ ГЕЙТА, и ни один не косметический:
      * личность объявила слот `vision` — иначе пере-просмотр шёл бы всегда и удваивал
        стоимость каждой картинки;
      * у вложения есть `source_url` — иначе ветка падала бы на старых тредах и на
        вложениях, пришедших без ссылки;
      * это картинка — у остальных модальностей пере-смотреть нечего.

    Результат дописывается К нейтральному описанию, а не заменяет его: нейтральное нужно
    и общему агенту, и следующим сообщениям, где личность может быть уже другой.

    Fail-soft на всём пути: протухшая ссылка, недоступное хранилище, сбой VLM — работаем
    по тому, что есть. Отказ пере-просмотра не должен ронять анализ вложения.
    """
    from service.domain import persona

    resolved_execution = require_execution(
        execution if isinstance(execution, RunExecutionContext) else None
    )

    if att.kind != "image":
        return att.content
    focus = persona.current().slot("vision")
    if not focus or not att.source_url:
        return att.content

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(att.source_url)
            if resp.status_code >= 400 or len(resp.content) > _RELOOK_MAX_BYTES:
                logger.info("пере-просмотр пропущен: HTTP %s / размер", resp.status_code)
                return att.content
            data = resp.content

        from service.domain.media import describe_image

        extra = await describe_image(
            data,
            resp.headers.get("content-type") or "image/png",
            att.name or "image",
            focus=focus,
            execution=resolved_execution,
        )
    except Exception:  # noqa: BLE001
        logger.info("image review unavailable", extra={"failure_code": "unavailable"})
        return att.content

    if not str(extra or "").strip():
        return att.content
    return f"{att.content}\n\n## Взгляд под выбранную специализацию\n{extra}"


@step_timing.measure("modality_fanout")
async def run_modality_fanout(
    *,
    attachments: list[ModalityAttachment],
    user_input: str,
    execution: RunExecutionContext | None = None,
) -> tuple[str, list[AgentEvent]]:
    """Параллельно проанализировать модальности и собрать агрегированный контекст.

    Возвращает (aggregated_context, trace_events). Контекст затем подмешивается в
    эффективный вход general-агента.
    """
    events: list[AgentEvent] = [
        AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name="multimodal",
            data=f"Параллельный анализ модальностей: {len(attachments)}",
            metadata={"modalities": [a.kind for a in attachments]},
        )
    ]
    execution = require_execution(execution)
    usage_cursor = execution.usage.cursor()

    async def _analyze(att: ModalityAttachment):
        analyst = get_modality_analyst(att.kind)
        content = await _content_for_persona(att, execution)
        analysis = await analyst.analyze(
            user_input=user_input,
            name=att.name,
            content=content,
            execution=execution,
        )
        return att, analysis

    results = await asyncio.gather(*[_analyze(att) for att in attachments], return_exceptions=True)

    blocks: list[str] = []
    degraded: list[str] = []
    for att, res in zip(attachments, results, strict=False):
        # ⚠️ BaseException, А НЕ Exception: `gather(return_exceptions=True)` кладёт сюда
        # `CancelledError`, наследующую BaseException. Отмена ОДНОГО аналитика роняла весь
        # запрос вместе с уже оплаченными разборами остальных вложений — и это был
        # единственный реальный вход сюда, обычные Exception аналитик глушит сам.
        if isinstance(res, BaseException):
            logger.warning(
                "Разбор вложения '%s' не удался (%s) — в контекст уйдёт сырой файл",
                att.kind,
                "unavailable",
            )
            # Обрезаем так же, как это делает фолбэк внутри аналитика: иначе сырой дамп
            # многостраничного файла вытеснит из окна остальные вложения.
            analysis = trim_text_to_tokens(str(att.content or ""), _RAW_FALLBACK_TOKENS)
            degraded.append(att.name or att.kind)
        else:
            _, analysis = res

        title = _KIND_TITLES.get(att.kind, "Вложение")
        label = f"{title}: {att.name}".strip().rstrip(":").strip()
        # STATUS_UPDATE, а не TOOL_CALL_COMPLETE: на tool-событии сериализатор кладёт
        # `data` ещё и в `tool_name`, и фронт печатал два ярлыка об одном в одной строке.
        # ⚠️ Статус НЕ ВРЁТ про деградацию: безусловное «Разобрано» показывало зелёную
        # галочку и там, где в контекст ушёл сырой файл, — связать это с падением
        # качества было нечем.
        failed = att.name in degraded or att.kind in degraded
        events.append(
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="multimodal",
                data=(f"Без разбора (сырой текст) — {label}" if failed else f"Разобрано — {label}"),
                metadata={
                    "kind": att.kind,
                    "name": att.name,
                    "chars": len(str(analysis or "")),
                    **({"degraded": "analyst_failed"} if failed else {}),
                },
            )
        )
        if str(analysis or "").strip():
            # 🔴 Для картинки в блок едет ПЕРЕСКАЗ описания, сделанный аналитиком: рамку
            # источника он мог не повторить, а отвечающая модель пикселей не видит вовсе.
            # Без пометки заголовок «### Изображение: photo.png» читается как «картинка
            # приложена», и на «опиши подробно» модель достраивает детали.
            body = str(analysis).strip()
            if att.kind == "image":
                body = frame_description(att.name or "изображение", body)
            blocks.append(f"### {label}\n{body}")

    # Тарификация веера: один token_usage-событие на все LLM-вызовы аналитиков.
    # ReplyAssembler.consume суммирует его как любой другой usage; без него N
    # анализов вложений уходили мимо биллинга (аудит: fan-out был бесплатным).
    fanout_usage = execution.usage.project_kind_since(usage_cursor, UsageKind.MULTIMODAL)
    if fanout_usage["calls"]:
        events.append(
            AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name="multimodal",
                data="",
                metadata={
                    "token_usage": {
                        "prompt": fanout_usage.get("prompt", 0),
                        "completion": fanout_usage.get("completion", 0),
                        "total": fanout_usage.get("total", 0),
                        "model": fanout_usage.get("model"),
                    },
                    "kind": "multimodal_usage",
                },
            )
        )

    aggregated = ""
    if blocks:
        aggregated = "## Агрегированный мультимодальный контекст\n" + "\n\n".join(blocks)
    return aggregated, events


async def fanout_context(
    attachments: list,
    user_input: str,
    file_context: str | None,
    *,
    execution: RunExecutionContext | None = None,
):
    """Параллельный разбор нескольких модальностей → один размеченный контекст.

    Готовит КОНТЕКСТ, а не делит задачу: с декомпозицией ортогонален. Здесь уже была
    регрессия — декомпозиция жила в `else` к этой ветке, и любые два вложения молча её
    отменяли: человек жал тумблер, прикладывал файлы и получал однопроходный ответ.
    """
    aggregated, events = await run_modality_fanout(
        attachments=attachments,
        user_input=user_input,
        execution=execution,
    )
    merged = "\n\n".join(part for part in (aggregated, file_context) if part)
    return merged, events
