"""Deep research sub-agent."""

import logging
import re
from collections.abc import AsyncGenerator

from service.domain.capabilities.agent_spec import COST_EXPENSIVE, AgentSpec
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.research.ldr_adapter import (
    classify_ldr_failure,
    close_ldr_run,
    ldr_usage_receipt,
)
from service.domain.subagents.research.prompts import RU_REWRITE_SYSTEM
from service.domain.subagents.research_labels import status_info
from service.domain.subagents.utils import (
    pick_answer_model,
    pick_meta_model,
)
from service.domain.usage_ledger import UsageKind
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext

logger = logging.getLogger(__name__)

# Стратегии поиска LDR, которые имеет смысл отдавать пользователю. Внутренние
# (`news`) и снятые (`mcp`, `agentic`) сюда НЕ входят. Список сверен с
# `search_system_factory.create_strategy` — он на неизвестное имя не падает, а
# молча берёт `source-based`, поэтому имена валидируем у себя.
LDR_STRATEGIES = frozenset(
    {"langgraph-agent", "source-based", "focused-iteration", "topic-organization"}
)
DEFAULT_LDR_STRATEGY = "langgraph-agent"


class DeepResearchAgent(BaseSubAgent):
    """Specialized agent for deep research flows."""

    def __init__(self, model_settings: dict):
        super().__init__(
            name="deep_research",
            instructions=(
                "Проводи глубокий ресерч: формируй гипотезы, собирай источники, "
                "сопоставляй точки зрения и выдавай структурированный аналитический "
                "отчёт с выводами."
            ),
            model_settings=model_settings,
        )

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Запускаю глубокий ресерч")

        safety = await self.evaluate_input_safety(user_input)
        if safety["sensitive"]:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data=(
                    "⚠️ Обнаружена чувствительная тема — применяю усиленные "
                    "guardrails и нейтральный тон."
                ),
                metadata=safety["meta"],
            )
        if safety["blocked"]:
            yield AgentEvent(
                type=EventType.ERROR,
                agent_name=self.name,
                data=safety["message"],
                metadata=safety["meta"],
            )
            yield self.complete_event("Ресерч остановлен guardrails")
            return

        execution = require_execution()
        usage_cursor = execution.usage.cursor()
        meta: dict = {"model": None, "emitted": 0}

        provider = self._resolve_provider()
        used_ldr = False
        # ⚠️ ОТКАТ НА НАТИВНЫЙ ПУТЬ ОБЯЗАН БЫТЬ ВИДЕН. Раньше о нём знал только лог
        # сайдкара: пользователь получал «Этап 1/4: составляю план исследования…» —
        # неотличимо от полноценного ресёрча — и платил за него, не зная, что движок
        # исследований не участвовал вовсе. Живая жалоба ровно об этом: «сработал
        # фоллбек, почему ldr недоступен?» — по ответу понять это было нельзя.
        degraded_reason: str | None = None
        if provider in ("auto", "ldr"):
            from service.infrastructure.integration.ldr_research import (
                LDRResearchClient,
                LDRUnavailableError,
            )

            client = LDRResearchClient(**self._resolve_ldr_settings())
            if not client.available:
                # Не настроен вовсе (нет адреса/логина/пароля) — самый тихий из путей:
                # сюда не попадал даже WARNING, потому что до попытки не доходило.
                degraded_reason = "движок исследований не настроен"
                logger.warning("LDR не настроен, откат на нативный ресёрч")
            if client.available:
                try:
                    async for event in self._run_ldr(client, user_input, context, execution, meta):
                        yield event
                    used_ldr = True
                except LDRUnavailableError as exc:
                    # LDR недоступен/сбой/дедлайн — откатываемся на нативный путь
                    # (аналог noop-фолбэка памяти; чат не должен ломаться).
                    failure = classify_ldr_failure(exc)
                    degraded_reason = "движок исследований недоступен"
                    logger.warning("LDR fallback with bounded code '%s'", failure.code.value)
                except Exception as exc:  # noqa: BLE001
                    failure = classify_ldr_failure(exc)
                    degraded_reason = "движок исследований недоступен"
                    logger.warning("LDR fallback with bounded code '%s'", failure.code.value)
                finally:
                    # ⚠️ Отмена должна доехать до LDR: закрыть свой клиент мало —
                    # исследование продолжает жечь токены через наш шлюз `/v1`, который
                    # не тарифицирует. Провайдер списывает с нас, мы — ни с кого.
                    #
                    # `shield` — против ПОВТОРНОЙ отмены (шатдаун, добивающий задачи):
                    # она убила бы сам запрос на terminate. Таймаут — чтобы висящий LDR
                    # не задерживал освобождение воркера.
                    cleanup_failure = await close_ldr_run(client)
                    if cleanup_failure is not None:
                        logger.warning(
                            "LDR cleanup failed with bounded code '%s'",
                            cleanup_failure.code.value,
                        )

        if not used_ldr:
            if degraded_reason:
                yield AgentEvent(
                    type=EventType.STATUS_UPDATE,
                    agent_name=self.name,
                    data=(
                        f"⚠️ Глубокое исследование выполняется упрощённым путём: "
                        f"{degraded_reason}. Результат будет менее полным."
                    ),
                    metadata={"degraded": True, "degraded_reason": degraded_reason},
                )
            async for event in self._run_native(user_input, context, execution, meta):
                yield event

        # token_usage в AGENT_COMPLETE — иначе reply_assembler не начислит кредиты
        # за ресёрч (реальные LLM-вызовы: LDR-метрики либо план+синтез).
        completion_meta = self._usage_meta(execution, usage_cursor, meta["model"], meta["emitted"])
        if degraded_reason:
            # Пометка едет и в метаданных: событие можно не увидеть (свернули трейс,
            # сторонний клиент). ⚠️ `_usage_meta` возвращает None, когда платных вызовов
            # не было — разворачивать None нельзя, падение унесло бы весь прогон.
            completion_meta = {
                **(completion_meta or {}),
                "degraded": True,
                "degraded_reason": degraded_reason,
            }
        yield self.complete_event("Глубокий ресерч завершён", completion_meta)

    @staticmethod
    def _resolve_provider() -> str:
        from service.settings import config
        from service.shared.agent_settings import runtime_settings

        raw = runtime_settings.get_agents(
            "deep_research_provider", config.agents.deep_research_provider
        )
        value = str(raw or "auto").strip().lower()
        return value if value in {"auto", "ldr", "native"} else "auto"

    def _resolve_ldr_settings(self) -> dict:
        """Настройки LDR: per-user → overlay (админка) → config.

        Раньше клиент строился без аргументов и читал config НАПРЯМУЮ, минуя
        runtime-overlay — админский `agents.ldr_model` не применялся.
        ⚠️ `search_engines` страдал ровно тем же и был пропущен при той починке:
        его тут не было вовсе, клиент брал `config.agents.ldr_search_engines`, и
        смена движка в админке НЕ ДОЕЗЖАЛА до запроса. Теперь доезжает.

        Per-user: модель и стратегия. Движок — сознательно только админский: под
        стратегией `langgraph-agent` (наш дефолт) он почти ни на что не влияет —
        она регистрирует инструменты `search_<движок>` по всем доступным движкам и
        выбирает их динамически, а `search_engine` задаёт лишь ОСНОВНОЙ.
        """
        from service.settings import config
        from service.shared.agent_settings import runtime_settings

        per_user = self.model_settings or {}
        model = per_user.get("ldr_model") or runtime_settings.get_agents(
            "ldr_model", config.agents.ldr_model
        )
        strategy = per_user.get("ldr_strategy") or runtime_settings.get_agents(
            "ldr_strategy", config.agents.ldr_strategy
        )
        return {
            "model": model,
            "strategy": self._sanitize_strategy(strategy),
            "search_engines": runtime_settings.get_agents(
                "ldr_search_engines", config.agents.ldr_search_engines
            ),
            "iterations": runtime_settings.get_agents(
                "ldr_iterations", config.agents.ldr_iterations
            ),
        }

    @staticmethod
    def _sanitize_strategy(raw) -> str:
        """Отсеять стратегию, которой у LDR нет.

        ⚠️ Проверка нужна именно ЗДЕСЬ: `search_system_factory` на незнакомое имя
        не падает, а МОЛЧА откатывается на `source-based` (лишь warning в чужих
        логах). Пользователь при этом получил бы совсем другой — более дешёвый и
        мелкий — ресёрч, будучи уверенным, что выбрал глубокий. Опечатка в
        per-user настройке не должна тихо подменять продукт.
        """
        value = str(raw or "").strip().lower()
        if value in LDR_STRATEGIES:
            return value
        if value:
            logger.warning(
                "неизвестная стратегия LDR %r — беру дефолтную %s", value, DEFAULT_LDR_STRATEGY
            )
        return DEFAULT_LDR_STRATEGY

    async def _run_native(
        self,
        user_input: str,
        context: UserContext,
        execution: RunExecutionContext,
        meta: dict,
    ) -> AsyncGenerator[AgentEvent]:
        """Нативный deep_research() (fallback / provider=native)."""
        try:
            from service.domain.client import list_qualified_models
            from service.domain.subagents.context_query import (
                build_standalone_query,
            )
            from service.domain.tools.deep_research import ResearchProgress, deep_research

            models = await list_qualified_models()
            model = pick_answer_model(models, self.preferred_model())
            meta["model"] = model
            if not model:
                yield self.error_event("Нет доступной модели для ресерча")
                return
            # Раскрываем follow-up в самостоятельную тему по истории диалога —
            # иначе ресёрч уходит исследовать буквальный текст, теряя контекст.
            topic = await build_standalone_query(user_input, context, model, execution=execution)
            async for chunk in deep_research(topic, model):
                # Вехи хода — статус-события с тем же контрактом, что у пути через LDR
                # (`kind=research_progress` + процент): фронт рисует их прогресс-баром.
                # Раньше нативный путь печатал их ТЕКСТОМ в тело отчёта, и «Этап 2/4»,
                # «🔍 Поиск 1/4», «📄 Читаю…» оставались в сохранённом сообщении навсегда.
                if isinstance(chunk, ResearchProgress):
                    yield AgentEvent(
                        type=EventType.STATUS_UPDATE,
                        agent_name=self.name,
                        data=chunk.label,
                        metadata={
                            "kind": "research_progress",
                            "progress": chunk.progress,
                            "label": chunk.label,
                            "stage": chunk.stage,
                            "status": chunk.status,
                            **({"failure_code": chunk.failure_code} if chunk.failure_code else {}),
                        },
                    )
                    continue
                text = str(chunk)
                meta["emitted"] += len(text)
                yield await self.stream_text_event(text)
        except Exception:  # noqa: BLE001
            logger.warning("Native research failed with bounded code 'internal'")
            yield self.error_event(
                "Исследование завершилось безопасно обработанной ошибкой. "
                "Попробуйте уточнить тему или повторить позже."
            )

    async def _run_ldr(
        self,
        client,
        user_input: str,
        context: UserContext,
        execution: RunExecutionContext,
        meta: dict,
    ) -> AsyncGenerator[AgentEvent]:
        """Путь через микросервис LDR: старт → опрос (STATUS_UPDATE) → отчёт → метрики.

        Любая инфраструктурная проблема поднимает LDRUnavailableError выше — там
        произойдёт откат на нативный путь.
        """
        from service.domain.client import list_qualified_models
        from service.domain.subagents.context_query import build_standalone_query

        meta["model"] = client.model
        aux_model = None
        # Раскрываем follow-up в самостоятельную тему (дешёвый вызов НАШЕЙ модели;
        # его токены тоже попадут в общий ledger). aux_model переиспользуем ниже для
        # русификации отчёта.
        try:
            models = await list_qualified_models()
            # Модель ПОЛЬЗОВАТЕЛЯ, а не дешёвый дефолт: этот же aux русифицирует
            # отчёт, то есть пишет текст, который человек читает. Та же правка, что
            # в генераторе картинок, — и та же жалоба «выбрал модель, отвечает другая».
            aux_model = pick_meta_model(models, self.preferred_model())
            topic = await build_standalone_query(
                user_input, context, aux_model, execution=execution
            )
        except Exception:  # раскрытие темы — не критично, продолжаем с сырым вводом
            topic = user_input

        research_id = await client.start_research(topic)
        last_key = None
        last_label = "Идёт исследование"
        async for status in client.iter_status(research_id):
            progress, label = status_info(status)
            if label:
                last_label = label  # держим последнюю осмысленную веху LDR
            key = (progress, last_label)
            if key == last_key:  # не спамим одинаковыми апдейтами
                continue
            last_key = key
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data=last_label,
                # progress → прогресс-бар в трейс-панели; kind — маркер для фронта.
                metadata={"kind": "research_progress", "progress": progress, "label": last_label},
            )

        report = await client.report(research_id)
        summary = report.get("summary") or ""
        from service.domain.subagents.research import artifact_from_external_sources

        execution.artifacts.publish(
            "research.latest",
            artifact_from_external_sources(report.get("sources") or []),
            replace=True,
        )
        if not summary:
            # Пустой отчёт — считаем путь несостоявшимся, уходим на нативный.
            from service.infrastructure.integration.ldr_research import (
                LDRUnavailableError,
            )

            raise LDRUnavailableError("LDR вернул пустой отчёт")
        # Отчёт LDR обычно на английском (см. _RU_REWRITE_SYSTEM). Приводим к русскому
        # нашей моделью; уже русский отчёт не трогаем — экономим лишний вызов.
        if aux_model and not self._looks_russian(summary):
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data="Оформляю отчёт на русском",
                metadata={"kind": "research_progress", "label": "Оформляю отчёт на русском"},
            )
            summary = await self._rewrite_to_russian(summary, aux_model, execution)
        body = summary + self._format_sources(report.get("sources") or [])
        meta["emitted"] += len(body)
        yield await self.stream_text_event(body)

        # Реальные токены research → биллинг (иначе _usage_meta оценит по объёму).
        # BEST-EFFORT: отчёт пользователю УЖЕ отдан (yield выше). Сбой пост-обработки
        # метрик НЕ должен всплыть в process()→except и увести на нативный путь —
        # иначе пользователь получил бы ДВА отчёта (LDR + нативный), и оба платные.
        try:
            m = await client.metrics(research_id)
            receipt = ldr_usage_receipt(m, default_model=meta["model"])
            if receipt:
                from service.domain.usage_ledger import receipt_from_usage

                usage_receipt = receipt_from_usage(
                    receipt,
                    provider="ldr",
                    model=receipt.get("model"),
                    kind="research_synthesis",
                )
                execution.usage.record(usage_receipt)
                meta["model"] = receipt.get("model") or meta["model"]
        except Exception:  # noqa: BLE001
            logger.debug("LDR metrics failed with bounded code 'unavailable'")

    @staticmethod
    def _format_sources(sources: list) -> str:
        """`### Источники` из массива источников LDR (dict или строка)."""
        lines: list[str] = []
        for i, src in enumerate(sources, 1):
            if isinstance(src, dict):
                title = src.get("title") or src.get("name") or src.get("url") or f"Источник {i}"
                url = src.get("url") or src.get("link") or src.get("href") or ""
                lines.append(f"{i}. [{title}]({url})" if url else f"{i}. {title}")
            elif src:
                lines.append(f"{i}. {src}")
        return ("\n\n### Источники\n" + "\n".join(lines)) if lines else ""

    # Доля кириллицы в тексте, ниже которой отчёт считаем не-русским. Технические
    # токены (URL, названия алгоритмов, [n]) — латиницей, поэтому порог невысокий:
    # достаточно, чтобы отличить русскую прозу от англоязычной.
    _CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
    _LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)

    @classmethod
    def _looks_russian(cls, text: str) -> bool:
        cyr = len(cls._CYRILLIC_RE.findall(text or ""))
        lat = len(cls._LATIN_RE.findall(text or ""))
        total = cyr + lat
        if total == 0:
            return True  # только числа/пунктуация — переводить нечего
        return (cyr / total) >= 0.25

    @staticmethod
    async def _rewrite_to_russian(text: str, model: str, execution: RunExecutionContext) -> str:
        """Переписать отчёт LDR на русский нашей моделью. Fail-open: при любой ошибке
        или пустом ответе возвращаем оригинал (лучше англоязычный отчёт, чем сбой)."""
        from service.domain.client import create_chat_completion

        try:
            result = await invoke_model_call(
                create_chat_completion,
                messages=[
                    {"role": "system", "content": RU_REWRITE_SYSTEM},
                    {"role": "user", "content": text},
                ],
                model=model,
                kind=UsageKind.TRANSLATION,
                execution=execution,
                temperature=0.2,
                max_tokens=4096,
            )
        except Exception:  # noqa: BLE001
            logger.warning("LDR translation failed with bounded code 'unavailable'")
            return text
        out = first_message_content(result.response).strip()
        if not out:
            return text
        return out

    @staticmethod
    def _usage_meta(
        execution: RunExecutionContext,
        cursor: int,
        model: str | None,
        emitted_chars: int,
    ) -> dict | None:
        """Реальный usage провайдера, иначе — грубая оценка по объёму текста, чтобы
        ресёрч не оказался бесплатным для платформы."""
        usage_view = execution.usage.project_since(cursor)
        if usage_view["calls"]:
            return {
                "token_usage": {
                    "prompt": usage_view["prompt"],
                    "completion": usage_view["completion"],
                    "total": usage_view["total"],
                    "model": model,
                    "calls": usage_view["calls"],
                }
            }
        if emitted_chars > 0:
            est_completion = max(1, emitted_chars // 4)
            est_prompt = 1200  # план + синтез-промпты с собранными данными (грубо)
            receipt = execution.usage.record_usage(
                {"prompt": est_prompt, "completion": est_completion},
                provider="ldr",
                model=model,
                kind=UsageKind.RESEARCH_SYNTHESIS,
                estimated=True,
            )
            return {
                "token_usage": {
                    **receipt.as_dict(),
                }
            }
        return None


SPEC = AgentSpec(
    name="deep_research",
    label_ru="глубокое исследование",
    build=DeepResearchAgent,
    # 🔴 Сотни и тысячи кредитов за прогон: оркестратор его сам не запускает.
    billing_name="deep_research",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    prompt_hint=(
        "просят обзор с источниками, многостраничное исследование, «изучи тему».\n"
        "  Это самый дорогой режим и он идёт минуты. Не ставь его за «сравни» или "
        "«проанализируй»:\n"
        "  сравнение двух известных подходов — это general."
    ),
)
