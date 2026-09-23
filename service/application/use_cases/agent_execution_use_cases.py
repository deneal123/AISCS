from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from service.application.processor import AgentProcessor
from service.application.reply_assembler import ReplyAssembler
from service.application.route_contracts import build_provider_unavailable_reply
from service.contracts import RESULT_FIELDS  # noqa: F401 — ре-экспорт для совместимости
from service.domain import persona
from service.domain.capabilities import forced_allowlist, modality_conflict
from service.domain.routing.policy import canonical_route
from service.domain.run_context import RunExecutionContext
from service.domain.sessions import PseudoSession
from service.domain.tools.router import route_model
from service.events import EventType
from service.shared import deadline

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RouteModelUseCase:
    async def execute(
        self,
        *,
        text: str,
        selected_model: str | None,
        input_type: str | None,
        execution: RunExecutionContext,
    ) -> tuple[str | None, dict[str, Any]]:
        """Выбрать модель и записать вызов роутера напрямую в ledger прогона."""
        return await route_model(
            text=text,
            selected_model=selected_model,
            input_type=input_type,
            execution=execution,
        )


def _orchestrator_enabled() -> bool:
    """Включён ли авто-оркестратор (админ-снимок поверх конфига)."""
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    return bool(
        runtime_settings.get_agents(
            "auto_orchestrator_enabled", config.agents.auto_orchestrator_enabled
        )
    )


@dataclass(slots=True)
class PrepareExecutionContextUseCase:
    def execute(
        self,
        *,
        routing_meta: dict[str, Any],
        route_override: str | None,
        # Готовая категория авто-роутера из `/route`. Едет СКВОЗЬ, ничего здесь не решая:
        # эта функция разбирает ФОРСИРОВАНИЕ инструмента, а категория — это уже готовый
        # ответ роутера, и подмешивать её в логику форса нельзя (гейты мульти-интента и
        # планирования висят именно на `route_override`).
        resolved_category: str | None = None,
        web_search: bool,
        deep_research: bool,
        session_data: dict | None,
        thread_id: str,
        pseudo_session: Any | None,
        input_type: str | None = None,
    ) -> dict[str, Any]:
        route_override = canonical_route(route_override)
        resolved_category = canonical_route(resolved_category)
        # 🔴 ДОГАДКА РОУТЕРА МОДЕЛЕЙ РАЗВОРАЧИВАЕТСЯ, ТОЛЬКО ЕСЛИ ОРКЕСТРАТОР ВЫКЛЮЧЕН.
        #
        # Развёрнутая во флаги, она НЕОТЛИЧИМА от выбора человека, а на выбор человека
        # оркестратор не вызывается вовсе (`_blocking_reason`). То есть роутер моделей молча
        # перехватывал управление у «умного Авто» на каждом запросе, где говорил что-то
        # кроме «none»: решение принимал он, видя только текст — без контекста и истории.
        #
        # Оставлено ФОЛБЭКОМ для выключенного оркестратора: категорийного роутера больше
        # нет, и без этой ветки аварийный тумблер означал бы «маршрутизации нет вовсе».
        if (
            not _orchestrator_enabled()
            and not web_search
            and not deep_research
            and not route_override
        ):
            auto_tool = routing_meta.get("tool", "none")
            # Защита в глубину поверх `_guard_tool_modality` в `route_model`: маршрут,
            # которому нужна модальность, допускаем только при ней — иначе текстовый или
            # документный файл увёл бы на ASR-агент (эхо вместо анализа).
            if modality_conflict(auto_tool, input_type):
                auto_tool = "general"
            if auto_tool == "web_search":
                web_search = True
            elif auto_tool == "deep_research":
                deep_research = True
            elif auto_tool in forced_allowlist():
                # ⚠️ Множество ВЫВОДИТСЯ: перечисляя его руками, новый агент забывали здесь
                # последним — роутер уже умел его выбирать, а флаги не разворачивались.
                route_override = auto_tool
        return {
            "route_override": route_override,
            "resolved_category": resolved_category,
            "web_search": web_search,
            "deep_research": deep_research,
            "pseudo_session": pseudo_session
            or PseudoSession(session_id=(session_data or {}).get("session_id", thread_id)),
        }


@dataclass(slots=True)
class RunAgentUseCase:
    async def execute(
        self,
        *,
        processor: AgentProcessor,
        reply_assembler: ReplyAssembler,
        metadata: dict[str, Any],
        on_event: Any = None,
        **kwargs: Any,
    ) -> None:
        # События НЕ копим в список: каждое уже (1) стримится через on_event и (2)
        # потребляется reply_assembler.consume. Третья копия раньше уезжала в поле
        # `events` result-dict, которое НИКТО не читал (ни сайдкар, ни backend) — на
        # крупном ответе это тысячи repr-ов события впустую и в памяти, и в сериализации.
        async for event in processor.process_message_stream(**kwargs):
            if event.metadata:
                # token_usage — внутренний учёт, в наружную metadata не кладём (его
                # аккумулирует reply_assembler.consume). multi_intent_artifacts — сырые
                # b64-блобы под-шагов: их СПИСКОМ копит reply_assembler (_pending_artifacts),
                # сюда класть нельзя, иначе тяжёлый блоб утёк бы в metadata (аудит A4).
                metadata.update(
                    {
                        k: v
                        for k, v in event.metadata.items()
                        if k not in ("token_usage", "multi_intent_artifacts")
                    }
                )
            reply_assembler.consume(
                event=event,
                stream_chunk_type=EventType.STREAM_CHUNK,
                error_type=EventType.ERROR,
                structured_output_type=EventType.STRUCTURED_OUTPUT,
            )
            if on_event is not None:
                on_event(event)
            # 🔴 Мягкий дедлайн: перестаём ПОТРЕБЛЯТЬ события, но результат отдаём. Раньше
            # прогон обрывал внешний `wait_for`, и вместе с задачей отменялся накопленный
            # `per_call_usage` — вызовы, за которые платформа уже заплатила провайдеру, в
            # счёт не попадали вовсе. Обрыв здесь — это ЗАВЕРШЕНИЕ с пометкой, а не отмена.
            if deadline.must_finalize():
                logger.warning("Дедлайн прогона исчерпан — отдаём собранное как частичный ответ")
                metadata["deadline_exceeded"] = True
                break


# Порог «в этом ответе нечего дисклеймить». Приветствие и уточняющий переспрос короче;
# любой разбор, расклад или расчёт — длиннее в разы. Граница грубая намеренно: точного
# признака «здесь есть толкование» не существует, а ошибаться безопаснее в сторону
# ЛИШНЕГО дисклеймера, поэтому порог низкий.
_DISCLAIMER_MIN_CHARS = 220


def _note_declined_mode(reply: str, metadata: dict) -> str:
    """Дописать, что дорогой режим НЕ запускался, — ДЕТЕРМИНИРОВАННО.

    🔴 Тот же урок, что с оговорками личностей, и он подтвердился живым прогоном: просьбу
    в системном промпте («режим не запускался, не обещай его выполнить») модель ИГНОРИРУЕТ.
    На «проведи глубокое исследование» понижённый ответ всё равно начинался с «я проведу
    исследование…», хотя ресёрч не запускался и предложен кнопкой — человек видел кнопку и
    текст, который ей противоречит.

    ⚠️ Дубля не будет: если модель всё же сказала об этом сама, строку не добавляем.
    """
    offer = (metadata or {}).get("mode_offer") or {}
    label = str(offer.get("label") or "").strip()
    text = str(reply or "")
    if not label or not text.strip():
        return text
    if "не запуск" in text.lower():
        return text
    # ⚠️ ПРИПИСКА ГОВОРИТ РОВНО ТО, ЧЕГО НЕ ГОВОРИТ КАРТОЧКА. Здесь стояло «он дорогой,
    # запустите его кнопкой выше» — и цену, и кнопку карточка называет сама, а «выше» было
    # прямой неправдой: она рисуется ПОД текстом. Осталась одна вещь, которой в карточке
    # нет и которая нужна против «я проведу исследование…»: режим НЕ ЗАПУСКАЛСЯ.
    return f"{text}\n\n_⚠️ Режим «{label}» не запускался._"


def _ensure_disclaimers(reply: str) -> str:
    """Дописать оговорки личности, если модель их не вывела.

    🔴 ДЕТЕРМИНИРОВАННО, А НЕ ПРОСЬБОЙ В ПРОМПТЕ. Оговорки таролога, психолога и
    финансиста — юридически значимый текст («толкование не является финансовым советом»,
    «это не психотерапия»). Просьбу вывести строку модель выполняет как получится: в
    живом прогоне gpt-4o-mini проигнорировал её и в мягкой формулировке, и в жёсткой,
    на коротком уточняющем ответе. Текст такого класса не может зависеть от
    сговорчивости модели — иначе он «работает» ровно до первого дешёвого провайдера.

    Просьба в промпте при этом ОСТАЁТСЯ: когда модель её выполняет, оговорка стоит
    в связном месте ответа, а не приклеена в конец. Дубля не будет — проверяем вхождение.
    """
    text = str(reply or "")
    if len(text.strip()) < _DISCLAIMER_MIN_CHARS:
        # ⚠️ «Привет! Чем могу помочь?» — 24 символа, и снизу оговорка про то, что
        # толкование не является финансовым советом. Дисклеймер относится к ТОЛКОВАНИЮ;
        # в приветствии и в переспросе толковать нечего, и он читается как шум, который
        # быстро перестают замечать — включая те ответы, где он существен.
        return text
    missing = [d for d in persona.current().disclaimers if d and d not in text]
    if not missing:
        return text
    return f"{text.rstrip()}\n\n_{' '.join(missing)}_"


@dataclass(slots=True)
class PostprocessAgentReplyUseCase:
    def execute(
        self, *, reply_assembler: ReplyAssembler, metadata: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        reply = reply_assembler.build_reply()
        metadata = {**metadata, **reply_assembler.metadata}
        # ⚠️ ОШИБКА ШАГА ТЕРЯЛАСЬ, ЕСЛИ ОТВЕТ ВСЁ-ТАКИ СОБРАЛСЯ. `error_messages`
        # использовались ТОЛЬКО при пустом ответе. В мульти-интенте упавший шаг
        # подставляет в синтез «[Шаг не выполнен: …]», синтез выдаёт связный текст —
        # значит ответ непустой, и в результат, который backend персистит и показывает,
        # не попадало НИЧЕГО: ни признака, ни текста ошибки. Прогон выглядел полностью
        # успешным, а собран был без половины работы. ERROR-событие при этом уходило в
        # трейс, но трейс живёт отдельно от сохранённого итога.
        #
        # Ответ НЕ подменяем: пользователь получил осмысленный текст, и заменять его на
        # «провайдер недоступен» было бы хуже. Помечаем.
        has_failures = bool(reply_assembler.error_codes or reply_assembler.error_messages)
        failure_codes = list(dict.fromkeys(reply_assembler.error_codes or ["internal"]))[:5]
        if str(reply).strip() and has_failures:
            metadata = {
                **metadata,
                "partial_failure": True,
                # Потолок — на случай мульти-интента с большим числом шагов: metadata
                # уезжает в backend целиком, и неограниченный список раздул бы результат.
                "step_errors": failure_codes,
            }
        if not str(reply).strip():
            provider_error = failure_codes[0] if has_failures else None
            reply = build_provider_unavailable_reply(provider_error)
            metadata = {
                **metadata,
                "provider_unavailable": True,
                **({"provider_error": provider_error} if provider_error else {}),
            }
        # A single terminal status lets every consumer distinguish a complete answer
        # from a useful but interrupted one without reconstructing this from several
        # historical flags.  Keep the flags themselves for stored-chat compatibility.
        document_outcome = str(metadata.get("document_outcome") or "")
        if document_outcome == "failed":
            metadata["execution_status"] = "failed"
        elif document_outcome == "draft_ready":
            metadata["execution_status"] = "partial"
        elif document_outcome == "deferred":
            metadata["execution_status"] = "deferred"
        elif document_outcome == "completed":
            metadata["execution_status"] = "completed"
        elif metadata.get("provider_unavailable"):
            metadata["execution_status"] = "failed"
        elif metadata.get("deadline_exceeded"):
            metadata["execution_status"] = "timed_out"
        elif metadata.get("partial_failure"):
            metadata["execution_status"] = "partial"
        else:
            metadata["execution_status"] = "completed"
        return _note_declined_mode(_ensure_disclaimers(reply), metadata), metadata


@dataclass(slots=True)
class PersistSessionHistoryUseCase:
    def execute(
        self,
        *,
        reply: str,
        metadata: dict[str, Any],
        resolved_model: str,
        reply_assembler: ReplyAssembler,
        workspace_artifacts: list[dict] | None = None,
    ) -> dict[str, Any]:
        return {
            "reply": reply,
            "metadata": metadata,
            "resolved_model": resolved_model,
            "reply_parts_count": len(reply_assembler.reply_parts),
            "reply_chars_count": len(reply),
            "prompt_tokens": reply_assembler.prompt_tokens,
            "completion_tokens": reply_assembler.completion_tokens,
            "total_tokens": reply_assembler.total_tokens,
            "per_call_usage": list(reply_assembler.per_call_usage),
            # ⚠️ ОПИСЬ созданного в песочнице, а не байты: файлы забирает backend, у
            # которого есть хранилище. Пусто — песочницы не было или агент ничего не создал.
            "workspace_artifacts": list(workspace_artifacts or []),
        }
