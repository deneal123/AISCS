"""Base class for specialized sub-agents."""

import logging
from abc import abstractmethod
from collections.abc import AsyncGenerator

from service.domain.base import BaseAgent
from service.domain.text_stream import iter_stream_chunks
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext
from service.shared.token_budget import trim_text_to_tokens

logger = logging.getLogger(__name__)


class BaseSubAgent(BaseAgent):
    """Common base for domain-specific sub-agents."""

    def start_event(self, message: str) -> AgentEvent:
        return AgentEvent(type=EventType.AGENT_START, agent_name=self.name, data=message)

    def complete_event(self, message: str, metadata: dict | None = None) -> AgentEvent:
        return AgentEvent(
            type=EventType.AGENT_COMPLETE, agent_name=self.name, data=message, metadata=metadata
        )

    def error_event(self, message: str) -> AgentEvent:
        return AgentEvent(type=EventType.ERROR, agent_name=self.name, data=message)

    async def evaluate_input_safety(self, user_input: str) -> dict:
        """Run lightweight guardrails before expensive tool/model work.

        Returns shape:
        {
            "blocked": bool,
            "sensitive": bool,
            "meta": dict,
            "message": str | None,
        }
        """
        from service.domain.guardrails import (
            check_appropriate_language,
            check_forbidden_topics,
        )

        text = str(user_input or "")
        lowered = text.lower()

        abusive = await check_appropriate_language.guardrail_function(None, None, text)
        forbidden = await check_forbidden_topics.guardrail_function(None, None, text)

        sensitive_markers = (
            "секс",
            "сексуал",
            "эрот",
            "вибратор",
            "интим",
            "porn",
            "sex",
            "adult",
        )
        sensitive = any(marker in lowered for marker in sensitive_markers)

        blocked = bool(abusive.tripwire_triggered or forbidden.tripwire_triggered)
        message = None
        if blocked:
            message = (
                "Запрос затрагивает небезопасную тему. Переформулируйте вопрос "
                "в безопасном и образовательном формате."
            )

        meta = {
            **(
                {
                    "failure_code": "policy",
                    "category": "internal",
                    "retryable": False,
                    "status_family": "none",
                }
                if blocked
                else {}
            ),
            # guardrail_block помечает ERROR как СРАБАТЫВАНИЕ ГАРДРЕЙЛА (а не сбой агента),
            # чтобы run_with_reroute не обошёл блок, отдав запрос general-агенту (аудит
            # P0.4): иначе блокировка web_search/deep_research/… становилась no-op.
            "guardrail_block": blocked,
            "input_guardrails": {
                "abusive": {
                    "tripwire": bool(abusive.tripwire_triggered),
                    "info": abusive.output_info,
                },
                "forbidden_topics": {
                    "tripwire": bool(forbidden.tripwire_triggered),
                    "info": forbidden.output_info,
                },
                "sensitive_topic": {
                    "tripwire": sensitive,
                    "info": {"detected": sensitive},
                },
            },
        }

        return {
            "blocked": blocked,
            "sensitive": sensitive,
            "meta": meta,
            "message": message,
        }

    def extra_user_context(self, context: UserContext, *, max_tokens: int = 800) -> str:
        """Собранный пайплайном контекст пользователя (память/знания/план), обрезанный.

        Спец-субагенты (web_search/deep_research/…) раньше видели только
        history_messages и игнорировали system_context, куда пайплайн уже сложил факты
        о пользователе, его знания и план: follow-up вроде «сравни это с тем, что
        онлайн» уходил в веб без загруженного документа. Отдаём контекст ОБРЕЗАННЫМ,
        чтобы он помогал синтезу, но не вытеснял основную задачу субагента. Fail-open:
        любая беда → пустая строка.
        """
        try:
            raw = str(getattr(context, "system_context", "") or "").strip()
            if not raw:
                return ""
            return trim_text_to_tokens(raw, max_tokens)
        except Exception:  # noqa: BLE001
            logger.debug("subagent context unavailable", extra={"failure_code": "internal"})
            return ""

    def _chunk_event(self, text: str, metadata: dict | None = None) -> AgentEvent:
        """Build a STREAM_CHUNK event. Текст не модифицируется (markdown сохраняется)."""
        return AgentEvent(
            type=EventType.STREAM_CHUNK,
            agent_name=self.name,
            data=text,
            metadata={**(metadata or {})},
        )

    async def _evaluate_output_guardrail(self, text: str) -> dict:
        """Прогнать output-guardrail один раз и вернуть metadata (без правки текста)."""
        from service.domain.guardrails import fact_check_output

        try:
            fact_check = await fact_check_output.guardrail_function(None, None, text)
            return {
                "fact_check": {
                    "tripwire": bool(fact_check.tripwire_triggered),
                    "info": fact_check.output_info,
                }
            }
        except Exception:
            logger.debug("output guardrail unavailable", extra={"failure_code": "internal"})
            return {}

    def persona_fragment(self, slot: str) -> str:
        """Фрагмент активной личности для точки впрыска. `""` — личность здесь молчит.

        Живёт здесь по той же причине, что `preferred_model` и `extra_user_context`:
        иначе обращение к линзе повторялось бы в каждом субагенте по-своему, и однажды
        кто-то прочитал бы её мимо (получив личность, которая «настроена и не работает»).
        """
        from service.domain import persona

        return persona.current().slot(slot)

    def persona_wrap(self, base_prompt: str, slot: str) -> str:
        """Базовый промпт + фрагмент слота; БЕЗ личности возвращает промпт как есть.

        Именно поэтому вызов безопасно ставить в любую готовую строку-промпт: без
        активной личности она не меняется даже пробелом.
        """
        from service.domain import persona

        return persona.current().wrap(base_prompt, slot)

    def preferred_model(self) -> str | None:
        """Модель, выбранная пользователем, если субагенту её передали.

        Живёт здесь, а не разбирается на месте: `model_settings` — это dict, который
        приходит снаружи, и `.get("model")` вперемешку с проверкой типа повторялся бы
        в каждом субагенте по-своему.
        """
        settings = getattr(self, "model_settings", None)
        return settings.get("model") if isinstance(settings, dict) else None

    async def stream_text_event(self, text: str, metadata: dict | None = None) -> AgentEvent:
        """Emit a stream chunk; guardrail-результат идёт в metadata, текст не мутируется.

        Раньше предупреждение fact_check дописывалось прямо в текст чанка, что ломало
        markdown и дублировалось. Теперь оно только в metadata.guardrails — фронт
        показывает его один раз после полной сборки сообщения.
        """
        if not str(text or "").strip():
            # For streaming pipelines empty chunks are expected sometimes.
            return self._chunk_event(
                "", {**(metadata or {}), "guardrails": {"empty_chunk": {"tripwire": True}}}
            )

        guard = await self._evaluate_output_guardrail(text)
        meta = {**(metadata or {})}
        if guard:
            meta["guardrails"] = guard
        return self._chunk_event(text, meta)

    async def stream_text_chunks(
        self,
        text: str,
        metadata: dict | None = None,
        *,
        chunk_size: int = 220,
    ) -> AsyncGenerator[AgentEvent]:
        """Stream text as markdown-safe chunks (token-streaming UX).

        Guardrail прогоняется ОДИН раз на полном тексте (результат — в metadata
        первого чанка), а нарезка не рвёт markdown и сохраняет исходный текст
        целиком (склейка чанков == исходник).

        ⚠️ ``metadata`` ВЕШАЕТСЯ ТОЛЬКО НА ПЕРВЫЙ ЧАНК. Раньше она копировалась в
        каждый, и для артефактов это означало настоящие дубликаты: презентацию сюда
        отдают вместе с ``{"pptx_b64": …}``, текст на 5-7 слайдов заведомо длиннее
        ``chunk_size``, то есть один и тот же base64 уезжал 2-3 раза. В мульти-интенте
        сборщик кладёт артефакт из КАЖДОГО события — пользователь получал 2-3
        одинаковых файла; на одиночном маршруте тот же блоб просто ехал по проводу
        трижды (для презентации в 2 МБ это ~8 МБ вместо 2.7 МБ).

        Ловить это было нечем: все тестовые дублёры отдавали ровно один чанк.
        """
        source = str(text or "")
        if not source.strip():
            yield self._chunk_event(
                "", {**(metadata or {}), "guardrails": {"empty_chunk": {"tripwire": True}}}
            )
            return

        guard = await self._evaluate_output_guardrail(source)
        head = dict(metadata or {})
        if guard:
            head["guardrails"] = guard
        for chunk in iter_stream_chunks(source, chunk_size=chunk_size):
            yield self._chunk_event(chunk, head)
            head = {}

    @abstractmethod
    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        raise NotImplementedError
