"""Специализированные субагенты-аналитики для мультимодального fan-out.

Каждый аналитик берёт уже извлечённый на upload текст одной модальности
(VLM-описание изображения, транскрипт аудио, текст документа) вместе с запросом
пользователя и готовит сжатый релевантный анализ. Их выводы затем агрегируются и
передаются general-агенту для финального ответа.

Аналитики деградируют мягко: при недоступности модели/ошибке возвращают исходный
извлечённый текст, чтобы агрегированный контекст не терялся.
"""

from __future__ import annotations

import logging

from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.utils import pick_text_model
from service.domain.usage_ledger import UsageKind

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 8000
_MAX_TOKENS = 700


class ModalityAnalyst:
    """База для аналитиков отдельных модальностей."""

    kind = "document"
    title = "Документ"
    system_prompt = (
        "Ты аналитик контекста. Выдели из предоставленного материала факты, "
        "релевантные запросу пользователя, кратко и без воды. Не выдумывай данные."
    )

    def _system_for_run(self) -> str:
        """Системный промпт аналитика с надстройкой личности — НА ОДИН ПРОГОН.

        🔴 РЕЗУЛЬТАТ В ЛОКАЛЬНОЙ ПЕРЕМЕННОЙ, `self.system_prompt` НЕ МУТИРУЕТСЯ НИКОГДА.
        Аналитики — РАЗДЕЛЯЕМЫЕ синглтоны: `_ANALYSTS` создаётся на импорте, один
        экземпляр обслуживает все параллельные запросы процесса. Припиши личность к
        атрибуту — и она (а) утечёт в чужой запрос, (б) накопится повторами при каждом
        вызове. Отсюда же метод, а не `__init__`: линза известна только в момент прогона.

        Слот выбирается по виду материала (`analyst.image`, `analyst.audio`, …): у
        аналитика изображения это «что вытянуть из ГОТОВОГО описания». Сам угол зрения
        VLM — другой слот (`vision`), он применяется слоем ниже, на пикселях.
        """
        from service.domain import persona

        return persona.current().wrap(self.system_prompt, f"analyst.{self.kind}")

    async def analyze(
        self,
        *,
        user_input: str,
        name: str,
        content: str,
        execution: RunExecutionContext | None = None,
    ) -> str:
        text = str(content or "").strip()
        if not text:
            return ""
        if len(text) > _MAX_CONTENT_CHARS:
            text = text[:_MAX_CONTENT_CHARS].rstrip() + "\n...[обрезано]"

        try:
            from service.domain.client import (
                create_chat_completion,
                list_qualified_models,
            )

            models = await list_qualified_models()
            model = pick_text_model(models)
            if not model:
                return text  # деградация: отдаём исходный извлечённый текст

            result = await invoke_model_call(
                create_chat_completion,
                kind=UsageKind.MULTIMODAL,
                execution=require_execution(execution),
                messages=[
                    {"role": "system", "content": self._system_for_run()},
                    {
                        "role": "user",
                        "content": (
                            f"Запрос пользователя:\n{user_input}\n\n"
                            f"{self.title} ({name or 'без имени'}):\n{text}"
                        ),
                    },
                ],
                model=model,
                temperature=0.2,
                max_tokens=_MAX_TOKENS,
            )
            # Каждый аналитик — отдельный провайдерский LLM-вызов. Без учёта токенов
            # веер из N вложений тарифицировался мимо биллинга (аудит: fan-out был
            # бесплатным для юзера). accumulate_usage пишет модель для верной цены.
            resp = result.response
            reply = (first_message_content(resp)).strip()
            return reply or text
        except Exception:
            logger.warning("modality analyst failed code=internal")
            return text


class ImageContextAgent(ModalityAnalyst):
    kind = "image"
    title = "Изображение (описание)"
    system_prompt = (
        "Ты анализируешь текстовое описание изображения (результат VLM). "
        "Сформулируй, что изображено и какие детали важны для запроса пользователя. "
        "Опирайся только на описание, не домысливай содержимое изображения."
    )


class AudioContextAgent(ModalityAnalyst):
    kind = "audio"
    title = "Аудио (транскрипт)"
    system_prompt = (
        "Ты анализируешь транскрипт аудио. Извлеки суть и ключевые формулировки, "
        "релевантные запросу пользователя. Не выдумывай фраз, которых нет в транскрипте."
    )


class DocumentContextAgent(ModalityAnalyst):
    kind = "document"
    title = "Документ"
    system_prompt = (
        "Ты анализируешь текст документа. Выдели фрагменты и факты, релевантные "
        "запросу пользователя, кратко. Не выдумывай содержимое."
    )


class DataContextAgent(ModalityAnalyst):
    kind = "data"
    title = "Данные (таблица/структура)"
    system_prompt = (
        "Ты анализируешь структурированные данные (CSV/JSON/таблица). Опиши схему "
        "(колонки/ключи и типы), объём, и выдели строки/значения, релевантные запросу. "
        "Если уместно — отметь агрегаты (суммы, диапазоны, аномалии). Не выдумывай данные."
    )


class CodeContextAgent(ModalityAnalyst):
    kind = "code"
    title = "Исходный код"
    system_prompt = (
        "Ты анализируешь исходный код. Кратко опиши назначение, ключевые сущности "
        "(функции/классы/модули) и логику, релевантную запросу пользователя. "
        "Отметь потенциальные баги/риски, если они очевидны. Не выдумывай код."
    )


_ANALYSTS: dict[str, ModalityAnalyst] = {
    "image": ImageContextAgent(),
    "audio": AudioContextAgent(),
    "data": DataContextAgent(),
    "code": CodeContextAgent(),
    "document": DocumentContextAgent(),
}


def get_modality_analyst(kind: str) -> ModalityAnalyst:
    """Вернуть аналитика под модальность (document — безопасный дефолт)."""
    return _ANALYSTS.get(str(kind or "").lower(), _ANALYSTS["document"])
