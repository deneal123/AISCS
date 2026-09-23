"""Chunk-aware arbitrary post-processing over existing STT results."""

from __future__ import annotations

from dataclasses import dataclass, field

from service.domain.client import create_chat_completion
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.subagents.runtime import StageContext, StageRuntime
from service.domain.usage_ledger import UsageKind

from .models import TranscriptBatch, TranscriptChunk

_SYSTEM = (
    "Ты обрабатываешь уже полученный транскрипт и не выполняешь распознавание речи. "
    "Следуй задаче пользователя, сохраняй имена, числа, даты, цитаты и неопределённость. "
    "Не добавляй фразы, которых нет в переданном фрагменте. Верни только результат "
    "обработки этого фрагмента."
)


@dataclass(slots=True)
class PostprocessResult:
    sections: list[str] = field(default_factory=list)
    processed_chunks: int = 0
    total_chunks: int = 0
    partial: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(section for section in self.sections if section.strip()).strip()


class AudioPostprocessor:
    def __init__(self, *, model: str, stage_context: StageContext) -> None:
        self.model = model
        self.stage_context = stage_context

    async def process(self, task: str, batch: TranscriptBatch) -> PostprocessResult:
        chunks = batch.chunks()
        result = PostprocessResult(total_chunks=len(chunks))
        for chunk in chunks:
            if self.stage_context.should_stop:
                result.partial = True
                break
            outcome = await self._process_chunk(task, chunk)
            if not outcome.ok or not outcome.value:
                result.partial = True
                continue
            result.sections.append(outcome.value)
            result.processed_chunks += 1
        if result.processed_chunks < result.total_chunks:
            result.partial = True
        return result

    async def _process_chunk(self, task: str, chunk: TranscriptChunk):
        async def _call():
            return await invoke_model_call(
                create_chat_completion,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Задача:\n{task}\n\n"
                            f"Фрагмент {chunk.chunk_index + 1}/{chunk.chunk_count}:\n"
                            f"{chunk.text}"
                        ),
                    },
                ],
                model=self.model,
                kind=UsageKind.AUDIO_POSTPROCESS,
                temperature=0.2,
                max_tokens=1400,
            )

        runtime = StageRuntime(
            self.stage_context,
            stage="audio_postprocess",
            timeout_sec=90,
            input_count=1,
        )
        response = await runtime.run_model(_call)
        if not response.ok or response.value is None:
            return response
        text = first_message_content(response.value).strip()
        if not text:
            return type(response).failure(
                stage="audio_postprocess",
            )
        return type(response)(text, response.receipt, response.diagnostics)


def is_pure_transcription_task(task: str) -> bool:
    normalized = str(task or "").strip().lower()
    if not normalized:
        return True
    markers = (
        "распознай",
        "транскриб",
        "speech to text",
        "stt",
        "переведи в текст",
        "что сказано",
    )
    return len(normalized) < 180 and any(marker in normalized for marker in markers)


__all__ = ["AudioPostprocessor", "PostprocessResult", "is_pure_transcription_task"]
