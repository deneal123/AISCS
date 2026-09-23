"""Путь исполнения через Agents SDK: Responses-стрим + аварийный chat/completions.

⚠️ ПОЧЕМУ ЭТО ОТДЕЛЬНЫЙ ФАЙЛ. У агента ДВА разных пути исполнения, и они не варианты
одного алгоритма: SDK сам ведёт цикл инструментов и отдаёт свои события, а `chat_run.py`
стримит chat/completions напрямую и ведёт цикл сам. Пока оба лежали в одном классе,
`SimpleStreamingAgent` весил 741 строку, а метод-диспетчер — 236: в нём начало, гардрейлы,
выбор пути И полностью встроенный SDK-путь с аварийным фолбэком.

⚠️ Примесь, а не свободная функция: код переехал ПОБУКВЕННО, чтобы перенос проверялся
диффом, а не только зелёным набором. Это денежный путь — он отдаёт `token_usage`, из
которого backend списывает токены.

От класса-хозяина примесь требует: `name`, `instructions`, `tools`, `model_settings`,
`max_turns`, `input_guardrails`, `output_guardrails`, а также методы
`_compose_system_instructions`, `_build_input_items`, `_is_blocked_chat_model`,
`_pick_chat_capable_model`. Состав держит тест
`tests/test_agent_runner_mixins.py`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from service.domain.client import create_chat_completion, list_qualified_models
from service.domain.client.protocol import safe_failure_metadata
from service.domain.control_tokens import strip_control_tokens
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import require_execution
from service.domain.runners.sdk_setup import build_sdk_agent, wrap_sdk_context
from service.domain.runners.support import _resolve_chat_max_tokens
from service.domain.text_stream import iter_stream_chunks
from service.domain.usage_tracking import _extract_sdk_run_usage
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import estimate_tokens

logger = logging.getLogger(__name__)


def _describe_failure(exc: BaseException) -> str:
    """Compatibility facade returning only a bounded user-facing description."""

    code = str(safe_failure_metadata(exc).get("failure_code") or "remote")
    if code == "timeout":
        return "Request timed out. Please try again."
    if code in {"transport", "remote", "rate_limit"}:
        return "Provider temporarily unavailable. Please try again."
    return "Request could not be completed safely."


def _sdk_model(model_id: str) -> Any:
    """Модель для `Agent(model=...)` — ОБЪЕКТОМ, а не строкой.

    🔴 СТРОКА С `/` ЛОМАЕТ ЗАПРОС. SDK разбирает строку модели как `провайдер/модель`
    (конвенция `MultiProvider`), а у агрегаторов слеш — ЧАСТЬ ИМЕНИ: `openai/gpt-4o-mini`
    у RouterAI/OpenRouter. Живой прогон: строкой → `400 Model 'gpt-4o-mini' not found`
    (префикс съеден), объектом → 89 дельт стрима и рабочий вызов инструмента. Именно это,
    а не «ненадёжный Responses-стрим», делало SDK-путь неработоспособным у агрегаторов.

    Клиент берём тот же, что уже зарегистрирован как дефолтный при инициализации
    провайдера (`providers/runtime.py`), — иначе объект уехал бы к чужой базе и ключу.
    Fail-open: не смогли собрать объект — отдаём строку, поведение как прежде.
    """
    try:
        from agents import OpenAIChatCompletionsModel

        from service.domain.client.provider_compat import active_provider_client
        from service.domain.run_context import current_execution

        execution = current_execution()
        admission = execution.provider_admission if execution is not None else None
        if admission is not None:
            owner = admission.snapshot.owner_for(model_id)
            client = admission.snapshot.client_for(owner or admission.snapshot.active_provider)
        else:
            client = active_provider_client()
        if client is None:
            return model_id
        return OpenAIChatCompletionsModel(model=model_id, openai_client=client)
    except Exception:  # noqa: BLE001
        logger.debug("не удалось собрать модель-объект для SDK; отдаю строкой")
        return model_id


class SdkRunMixin:
    """Прогон через Agents SDK. Требования к хозяину — в докстринге модуля."""

    @staticmethod
    def _extract_text_from_sdk_event(event: Any) -> str | None:
        """Extract streaming token delta from SDK stream events.

        Only raw_response_event delta subtypes are extracted — never "done" or
        "completed" summaries, which would duplicate already-streamed tokens.
        """
        if event is None:
            return None

        event_type = getattr(event, "type", None) or (
            event.get("type") if isinstance(event, dict) else None
        )

        # Only extract streaming deltas from raw LLM response events.
        # All other event types (run_item_stream_event, agent_updated_stream_event)
        # are completion signals, not new text to stream.
        if event_type != "raw_response_event":
            return None

        raw = getattr(event, "data", None) if not isinstance(event, dict) else event.get("data")
        if raw is None:
            return None

        r_type = getattr(raw, "type", None) if not isinstance(raw, dict) else raw.get("type")
        # ТОЛЬКО текст, видимый пользователю: `function_call_arguments.delta` — это
        # JSON-аргументы вызова инструмента, и раньше он утекал в чат сырым.
        # ⚠️ Путь живой только для нативного OpenAI: остальные провайдеры уведены в
        # chat/completions ради реалтайм-стрима.
        if r_type not in {
            "response.output_text.delta",
            "response.refusal.delta",
        }:
            return None

        delta = getattr(raw, "delta", None) if not isinstance(raw, dict) else raw.get("delta")
        if not isinstance(delta, str) or not delta:
            return None
        # SDK-путь идёт мимо клиента с потоковым фильтром — чистим здесь.
        # ⚠️ Разрыв управляющего токена между дельтами тут НЕ лечится: по этому пути идёт
        # обычный стрим OpenAI, и разорванный токен до пользователя дойдёт.
        return strip_control_tokens(delta) or None

    async def _run_sdk_streamed(
        self, user_input: str, context: UserContext
    ) -> AsyncGenerator[AgentEvent]:
        """Стрим через Agents SDK; при сбое — аварийный chat/completions.

        ⚠️ Аварийная ветка не косметика: без неё сбой SDK означал бы ответ «ошибка» при
        живых провайдерах. И она ТАРИФИЦИРУЕТСЯ (`token_usage` в AGENT_COMPLETE) — иначе
        платформа платила бы провайдеру за ответ, за который не выставила счёт.
        """
        seq = 0
        # ⚠️ ОБЪЯВЛЕНЫ ДО try. Обработчику сбоя нужно знать, успел ли контент уйти
        # пользователю и что успел насчитать провайдер; внутри try эти имена могли
        # остаться несвязанными, и обработчик падал бы уже своим NameError.
        collected_text = ""
        streamed_chunks = 0
        result = None
        try:
            from agents import Agent as SDKAgent
            from agents import RunContextWrapper
            from agents import Runner as SDKRunner
        except ImportError:
            logger.error("Agents SDK import failed code=internal")
            yield AgentEvent(
                type=EventType.ERROR, agent_name=self.name, data="Agent SDK not available"
            )
            return

        try:
            from agents import ModelSettings

            agent = build_sdk_agent(
                self,
                context,
                agent_cls=SDKAgent,
                model_settings_cls=ModelSettings,
                model_factory=_sdk_model,
            )
            wrapped_context = wrap_sdk_context(context, wrapper_cls=RunContextWrapper)

            result = SDKRunner.run_streamed(
                agent,
                self._build_input_items(user_input, context),
                context=wrapped_context,
                max_turns=self.max_turns,
            )

            seq = 0
            tool_calls_seen = set()

            async for event in result.stream_events():
                seq += 1
                event_type = getattr(event, "type", None)

                # ⚠️ `debug` и ЛЕНИВОЕ форматирование, а не f-строка на `info`. f-строка
                # вычисляется БЕЗУСЛОВНО, то есть `str(event)` — полный repr модели SDK —
                # выполнялся на КАЖДУЮ дельту стрима. На ответе в 2000 токенов это тысячи
                # форматирований и столько же строк в логе.
                logger.debug("SDK event type=%s", event_type)

                if event_type == "run_item_stream_event":
                    item = getattr(event, "item", None)
                    if item:
                        tool = getattr(item, "tool", None) or getattr(item, "tool_name", None)
                        if tool:
                            tool_name = getattr(tool, "name", str(tool))
                            if tool_name not in tool_calls_seen:
                                tool_calls_seen.add(tool_name)
                                yield AgentEvent(
                                    type=EventType.TOOL_CALL_START,
                                    agent_name=self.name,
                                    data=f"Using tool: {tool_name}",
                                    metadata={"tool_name": tool_name},  # чистое имя, без префикса
                                    seq=seq,
                                )

                chunk_text = self._extract_text_from_sdk_event(event)

                if chunk_text:
                    collected_text += chunk_text
                    streamed_chunks += 1
                    yield AgentEvent(
                        type=EventType.STREAM_CHUNK, agent_name=self.name, data=chunk_text, seq=seq
                    )

            if streamed_chunks == 0:
                final_output = getattr(result, "final_output", None)
                fallback_text = final_output if isinstance(final_output, str) else None
                if not fallback_text and final_output is not None:
                    fallback_text = str(final_output)
                fallback_text = fallback_text or ""
                collected_text = fallback_text

                for part in iter_stream_chunks(fallback_text):
                    seq += 1
                    yield AgentEvent(
                        type=EventType.STREAM_CHUNK,
                        agent_name=self.name,
                        data=part,
                        seq=seq,
                    )

            usage_model = (
                self.model_settings.get("model") if isinstance(self.model_settings, dict) else None
            )
            sdk_usage = _extract_sdk_run_usage(
                result,
                execution=require_execution(),
                model=usage_model,
            )
            complete_metadata: dict[str, Any] = {}
            if sdk_usage:
                complete_metadata["token_usage"] = {**sdk_usage, "model": usage_model}
            elif collected_text.strip():
                complete_metadata["token_usage"] = self._estimated_usage(
                    user_input=user_input,
                    collected_text=collected_text,
                    context=context,
                    usage_model=usage_model,
                )
            yield AgentEvent(
                type=EventType.AGENT_COMPLETE,
                agent_name=self.name,
                data=f"Completed {self.name}",
                metadata=complete_metadata,
            )

        except Exception as exc:
            failure = safe_failure_metadata(exc)
            logger.warning("SDK execution failed code=%s", failure["failure_code"])
            async for event in self._handle_sdk_failure(
                exc=exc,
                user_input=user_input,
                seq=seq,
                streamed_chunks=streamed_chunks,
                result=result,
                context=context,
            ):
                yield event

    def _estimated_usage(
        self,
        *,
        user_input: str,
        collected_text: str,
        context: UserContext | None,
        usage_model: str | None,
    ) -> dict[str, Any]:
        """Оценка счёта, когда SDK не сообщил usage.

        Без неё путь был бы БЕСПЛАТНЫМ при живой трате у провайдера (раньше здесь всегда
        стоял ноль, даже на успехе).

        ⚠️ СЧИТАЕМ ПО ТОМУ ЖЕ ПРОМПТУ, ЧТО РЕАЛЬНО УШЁЛ. Считалось по сырым
        `self.instructions` — то есть БЕЗ `system_context` (факты о пользователе, вложения
        текущей задачи, знания, план, резюме диалога), а он в живом запросе бывает в разы
        больше самих инструкций. Недобилл был систематическим и ровно там, где оценка и
        нужна: у провайдеров без stream-usage (mws/gigachat), которым эта ветка и служит.
        """
        est_prompt = estimate_tokens(self._compose_system_instructions(context))
        est_prompt += estimate_tokens(user_input)
        est_completion = estimate_tokens(collected_text)
        return {
            "prompt": est_prompt,
            "completion": est_completion,
            "total": est_prompt + est_completion,
            "model": usage_model,
            "estimated": True,
        }

    async def _handle_sdk_failure(
        self,
        *,
        exc: Exception,
        user_input: str,
        seq: int,
        streamed_chunks: int,
        result: Any,
        context: UserContext | None = None,
    ) -> AsyncGenerator[AgentEvent]:
        """Сбой SDK-прогона: доиграть частичное ЛИБО заменить аварийным прогоном."""
        # ⚠️ Контент уже ушёл — аварийный прогон запрещён: сбой SDK после нескольких дельт
        # запускал полный второй вызов поверх показанного. Пользователь видел ответ
        # дважды, платформа платила дважды.
        if streamed_chunks:
            async for event in self._finalize_partial_sdk_run(result, exc):
                yield event
            return

        # Аварийная ветка живёт отдельным методом: она сама по себе — целый прогон со
        # своим подбором модели, своим стримом и своим учётом токенов, и внутри `except`
        # читалась как продолжение основного пути, хотя это его замена.
        recovered = False
        async for event in self._emergency_chat_fallback(user_input, seq, context):
            recovered = recovered or event.type == EventType.AGENT_COMPLETE
            yield event
        if recovered:
            return

        failure = safe_failure_metadata(exc)
        yield AgentEvent(
            type=EventType.ERROR,
            agent_name=self.name,
            data="Выполнение завершилось безопасно обработанной ошибкой.",
            metadata={
                **failure,
                "category": "provider",
                "status_family": failure.get("status_family", "none"),
            },
        )

    async def _finalize_partial_sdk_run(
        self, result: Any, exc: Exception
    ) -> AsyncGenerator[AgentEvent]:
        """Стрим SDK оборвался ПОСЛЕ отданных токенов: закрыть прогон и ВЫСТАВИТЬ СЧЁТ.

        ⚠️ Usage упавшего прогона терялся целиком. `Runner.run_streamed` — это цикл
        вызовов инструментов, и к моменту сбоя в `result.raw_responses` уже лежат
        завершённые `ModelResponse`, за которые провайдер выставил счёт нам. В `except`
        их никто не читал: аварийный фолбэк тарифицировал только СВОЙ вызов.

        Пометка о прерывании — не косметика: пользователь должен знать, что ответ
        оборван, иначе он примет его за полный. Форма та же, что на chat-пути
        (`chat_run.py`), чтобы деградация выглядела одинаково независимо от провайдера.
        """
        note = "\n\n_⚠️ Ответ прерван (сбой провайдера) и может быть неполным._"
        yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name=self.name, data=note, metadata={})

        failure = safe_failure_metadata(exc)
        metadata: dict[str, Any] = {
            "interrupted": True,
            "failure_code": failure["failure_code"],
        }
        usage_model = (
            self.model_settings.get("model") if isinstance(self.model_settings, dict) else None
        )
        partial = (
            _extract_sdk_run_usage(
                result,
                execution=require_execution(),
                model=usage_model,
            )
            if result is not None
            else {}
        )
        if partial:
            metadata["token_usage"] = {**partial, "model": usage_model}
        yield AgentEvent(
            type=EventType.AGENT_COMPLETE,
            agent_name=self.name,
            data=f"Completed {self.name} (interrupted)",
            metadata=metadata,
        )

    async def _emergency_chat_fallback(
        self, user_input: str, seq: int, context: UserContext | None = None
    ) -> AsyncGenerator[AgentEvent]:
        """Прямой chat-вызов, когда SDK-прогон упал целиком.

        ⚠️ Не косметика: без неё сбой SDK означал бы ответ «ошибка» при живых
        провайдерах. И она ТАРИФИЦИРУЕТСЯ — иначе платформа платит провайдеру за ответ,
        за который не выставила счёт.

        Ничего не отдаёт, если восстановиться не вышло: вызывающий по отсутствию
        AGENT_COMPLETE понимает, что надо отдавать ошибку.
        """
        try:
            selected_model = None
            if isinstance(self.model_settings, dict):
                selected_model = self.model_settings.get("model")

            if self._is_blocked_chat_model(selected_model):
                logger.warning("Blocked non-chat model in settings: %s", selected_model)
                selected_model = None

            if not selected_model:
                models = await list_qualified_models()
                selected_model = self._pick_chat_capable_model(models)

            if not selected_model:
                return

            fallback_result = await invoke_model_call(
                create_chat_completion,
                messages=[
                    # ⚠️ Через общую склейку, а не `self.instructions`: иначе аварийный
                    # ответ терял весь `system_context` — факты, вложения, план, резюме.
                    # Наружу это выглядит как «модель вдруг забыла мой файл».
                    {"role": "system", "content": self._compose_system_instructions(context)},
                    {"role": "user", "content": user_input},
                ],
                model=selected_model,
                kind=None,
                execution=require_execution(),
                temperature=0.7,
                max_tokens=_resolve_chat_max_tokens(),
            )
            fallback_response = fallback_result.response
            fallback_text = first_message_content(fallback_response)
            if not fallback_text.strip():
                return

            for part in iter_stream_chunks(fallback_text):
                seq += 1
                yield AgentEvent(
                    type=EventType.STREAM_CHUNK,
                    agent_name=self.name,
                    data=part,
                    metadata={"fallback_model": selected_model},
                    seq=seq,
                )

            seq += 1
            complete_meta: dict[str, Any] = {"fallback_model": selected_model}
            if fallback_result.usage.billable:
                complete_meta["token_usage"] = fallback_result.usage.as_dict()
            yield AgentEvent(
                type=EventType.AGENT_COMPLETE,
                agent_name=self.name,
                data=f"Completed {self.name}",
                metadata=complete_meta,
                seq=seq,
            )
        except Exception as exc:
            failure = safe_failure_metadata(exc)
            logger.warning("Fallback completion failed code=%s", failure["failure_code"])
