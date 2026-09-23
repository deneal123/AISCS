"""Compatibility facade and routed agent for structured audio transcripts."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from service.domain.capabilities.agent_spec import COST_PAID, AgentSpec
from service.domain.subagents.audio import AudioPostprocessor, extract_audio_batch
from service.domain.subagents.audio.postprocess import is_pure_transcription_task
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.runtime import StageContext
from service.domain.subagents.utils import pick_answer_model
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext


class AudioTranscriptionAgent(BaseSubAgent):
    """Process STT output without duplicating Whisper or silently truncating text."""

    def __init__(self, model_settings: dict):
        super().__init__(
            name="audio_transcribe",
            instructions=(
                "Показывай полный доступный транскрипт и выполняй дополнительную задачу "
                "только над результатом существующего media pipeline."
            ),
            model_settings=model_settings,
        )

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Запускаю обработку аудио")
        safety = await self.evaluate_input_safety(user_input)
        if safety["sensitive"]:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data="⚠️ Чувствительная тема: вывод ограничен безопасным форматом.",
                metadata=safety["meta"],
            )
        if safety["blocked"]:
            yield AgentEvent(
                type=EventType.ERROR,
                agent_name=self.name,
                data=safety["message"],
                metadata=safety["meta"],
            )
            yield self.complete_event("Обработка аудио остановлена guardrails")
            return

        user_task, batch = extract_audio_batch(user_input, context)
        if batch.empty:
            yield self.error_event(
                "Не найден аудиоконтекст или доступный транскрипт текущего вложения. "
                "Повторите загрузку или выберите другой файл."
            )
            yield self.complete_event("Обработка аудио завершена без транскрипта")
            return

        yield AgentEvent(
            type=EventType.TOOL_CALL_COMPLETE,
            agent_name=self.name,
            data=(
                f"Подготовлено транскриптов: {len(batch.transcripts)}, "
                f"символов: {batch.total_chars}"
            ),
            metadata={
                "transcript_count": len(batch.transcripts),
                "transcript_chars": batch.total_chars,
                "segment_count": batch.segment_count,
                "legacy_fallback": batch.legacy_fallback,
            },
        )
        full_transcript = batch.render_full()
        if is_pure_transcription_task(user_task):
            async for event in self.stream_text_chunks(full_transcript):
                yield event
            yield self.complete_event("Распознавание аудио завершено")
            return

        models = await self._available_models_safe()
        model = pick_answer_model(models, self.preferred_model())
        if not model:
            async for event in self.stream_text_chunks(full_transcript):
                yield event
            yield self.complete_event(
                "Транскрипт готов; дополнительная обработка недоступна",
                {"postprocess_status": "unavailable"},
            )
            return

        stages = StageContext()
        processed = await AudioPostprocessor(model=model, stage_context=stages).process(
            user_task, batch
        )
        output = full_transcript
        if processed.text:
            output += f"\n\n---\n\n### Результат обработки\n\n{processed.text}"
        if processed.partial:
            output += (
                "\n\n_Дополнительная обработка выполнена частично; полный исходный "
                "транскрипт сохранён выше._"
            )
        async for event in self.stream_text_chunks(output):
            yield event
        completion_meta = {
            "audio": {
                "transcript_count": len(batch.transcripts),
                "processed_chunks": processed.processed_chunks,
                "total_chunks": processed.total_chunks,
                "partial": processed.partial,
            }
        }
        if stages.usage.receipts:
            completion_meta["token_usage"] = stages.usage.as_token_usage()
        yield self.complete_event("Обработка аудио завершена", completion_meta)

    @staticmethod
    async def _available_models_safe() -> list[str]:
        try:
            from service.domain.client import list_qualified_models

            return await list_qualified_models()
        except Exception:  # noqa: BLE001
            return []


SPEC = AgentSpec(
    name="audio_transcribe",
    label_ru="распознавание речи",
    build=AudioTranscriptionAgent,
    routable=False,
    decomposable=False,
    requires_input_type="audio",
    forced_by_input_type=("audio",),
    input_type_beats_toggles=True,
    billing_name="audio_transcribe",
    cost_class=COST_PAID,
)


__all__ = ["AudioTranscriptionAgent", "SPEC"]
