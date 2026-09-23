"""PPTX generation sub-agent."""

import base64
import logging
from collections.abc import AsyncGenerator

from service.domain.capabilities.agent_spec import COST_EXPENSIVE, AgentSpec
from service.domain.run_context import require_execution
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.utils import pick_answer_model
from service.domain.usage_ledger import UsageKind
from service.domain.usage_tracking import build_token_usage_meta
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext

logger = logging.getLogger(__name__)


def _visual_note(report: dict) -> str:
    """Честная строка о том, что с иллюстрациями. Пусто — когда всё получилось.

    ⚠️ Пользователь должен УЗНАТЬ, что дек вышел беднее задуманного. Молча отдать
    презентацию без картинок — это тот самый случай, когда деградация выглядит как
    штатная работа: файл есть, слайды есть, претензий не сформулировать.
    """
    asked, drawn = report.get("requested", 0), report.get("generated", 0)
    reasons = {
        "no_image_model": "у провайдера нет модели генерации изображений",
        "catalog_unavailable": "каталог моделей временно недоступен",
    }
    if not asked:
        reason = reasons.get(str(report.get("reason") or ""))
        return f"\n\n_Иллюстрации не добавлены: {reason}._" if reason else ""
    if drawn == asked:
        return ""
    if drawn == 0:
        return "\n\n_Иллюстрации сгенерировать не удалось — оформление текстовое._"
    return f"\n\n_Иллюстраций добавлено: {drawn} из {asked}._"


def _image_usage_meta(usage: dict, *, generated: int) -> dict | None:
    """Usage за иллюстрации: реальный от провайдера, иначе фикс-эквивалент за штуку.

    ⚠️ `model` ОБЯЗАТЕЛЕН: без него `resolve_model_price(None)` уходит в ДЕФОЛТ-цену
    вместо цены image-модели, и картинка тарифится по чужому тарифу (аудит P1.5).
    """
    from service.domain.tools.image_gen import fixed_equivalent_usage
    from service.domain.usage_tracking import build_token_usage_meta

    meta = build_token_usage_meta(usage)
    if meta is not None:
        return meta
    if generated > 0:
        return {"token_usage": fixed_equivalent_usage(usage.get("model"), generated)}
    return None


class PPTXGenerationAgent(BaseSubAgent):
    """Specialized agent for PPTX generation."""

    def __init__(self, model_settings: dict):
        super().__init__(
            name="pptx_gen",
            instructions=(
                "Создавай содержательные презентации PPTX с логичной структурой, "
                "ясными тезисами и фокусом на практическую ценность для аудитории."
            ),
            model_settings=model_settings,
        )

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Создаю структуру презентации...")

        safety = await self.evaluate_input_safety(user_input)
        if safety["sensitive"]:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data=(
                    "⚠️ Чувствительная тема: презентация будет в образовательном "
                    "и нейтральном формате."
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
            yield self.complete_event("Генерация PPTX остановлена guardrails")
            return

        execution = require_execution()
        usage_cursor = execution.usage.cursor()
        # Структуру планирует текстовая модель,
        # иллюстрации рисует image-модель, и цены у них разные. Один общий накопитель
        # означал бы, что всё посчитано по тарифу той модели, что записалась последней —
        # ровно так уже обжигался генератор изображений (аудит B5).
        images_generated = 0
        try:
            from service.domain.client import list_qualified_models
            from service.domain.tools.pptx import generate_pptx

            models = await list_qualified_models()
            model = pick_answer_model(models, self.preferred_model())
            if not model:
                yield self.error_event("Нет доступных моделей")
            else:
                # ⚠️ Здесь стояла ручная подмена model в mutable usage — компенсация за
                # то, что у `generate_pptx` была СВОЯ копия накопителя usage без
                # параметра `model`. Без компенсации `token_usage.model=None` → биллинг
                # брал дефолт-цену вместо реальной. Копия убрана, канон пишет модель
                # сам, и подпорка стала лишней: держать её значило бы оставить в коде
                # напоминание о дефекте, которого больше нет.
                yield AgentEvent(
                    type=EventType.TOOL_CALL_START,
                    agent_name=self.name,
                    data="Генерирую слайды с помощью ИИ...",
                )

                pptx_bytes, structure, images = await generate_pptx(
                    user_input, model, execution=execution
                )
                pptx_b64 = base64.b64encode(pptx_bytes).decode()
                slide_count = len(structure.get("slides", []))
                drawn, asked = images.get("generated", 0), images.get("requested", 0)
                images_generated = drawn

                yield AgentEvent(
                    type=EventType.TOOL_CALL_COMPLETE,
                    agent_name=self.name,
                    data=(
                        f"Презентация готова: {slide_count} слайдов, иллюстраций {drawn} из {asked}"
                        if asked
                        else f"Презентация готова: {slide_count} слайдов"
                    ),
                )

                reply = (
                    f"✅ **Презентация готова!** ({slide_count} слайдов)\n\n"
                    f"**Тема:** {structure.get('title', user_input)}\n\n"
                    + "\n".join(
                        f"- **Слайд {i + 1}:** {s.get('title', '')}"
                        for i, s in enumerate(structure.get("slides", []))
                    )
                    + _visual_note(images)
                    + "\n\n📎 Файл доступен для скачивания ниже."
                )

                async for chunk_event in self.stream_text_chunks(
                    reply,
                    metadata={
                        "pptx_b64": pptx_b64,
                        "filename": "presentation.pptx",
                        # ⚠️ Деградация помечается В МЕТАДАННЫХ, а не только в тексте.
                        # «Дек без картинок» иначе неотличим от «так и задумано» — ни
                        # для аналитики, ни для разбора жалобы.
                        **(
                            {"degraded": "illustrations_partial"} if asked and drawn < asked else {}
                        ),
                    },
                ):
                    yield chunk_event
        except Exception:
            logger.error("PPTX generation failed code=internal")
            yield self.error_event("Генерация презентации завершилась безопасной ошибкой.")

        # ⚠️ КАРТИНКИ ТАРИФИЦИРУЮТСЯ ОТДЕЛЬНЫМ СОБЫТИЕМ И СВОЕЙ МОДЕЛЬЮ.
        #
        # Положи мы их в общий mutable usage — весь запрос посчитался бы по цене той
        # модели, что записалась последней, то есть текстовой. А если провайдер
        # image-модальности не вернул usage (обычное дело), то без фикс-эквивалента
        # генерации просто БЕСПЛАТНЫ: вызов состоялся, платформа заплатила, счёт нулевой.
        # Ровно эти две ошибки уже разбирались в генераторе изображений (аудит B5, P1.5),
        # и повторять их в презентациях смысла нет.
        image_usage = execution.usage.project_kind_since(usage_cursor, UsageKind.PPTX_ILLUSTRATION)
        image_meta = _image_usage_meta(image_usage, generated=images_generated)
        if image_meta is not None:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data="",
                metadata={**image_meta, "kind": "pptx_illustration_usage"},
            )

        structure_usage = execution.usage.project_kind_since(usage_cursor, None)
        yield self.complete_event("Готово", build_token_usage_meta(structure_usage))


SPEC = AgentSpec(
    name="pptx_gen",
    label_ru="презентация",
    build=PPTXGenerationAgent,
    billing_name="pptx_gen",
    cost_class=COST_EXPENSIVE,
    confirm_by_default=True,
    routable=False,
    # One-cycle compatibility: new routing never advertises PPTX, but a saved
    # decomposition or an older model response may still name this step.
    decomposable=True,
    # ⚠️ Граница с цепочкой `research_deck` названа ЯВНО. Безусловное «просят презентацию»
    # перехватывало и те просьбы, где нужны свежие данные: подсказка соседа проигрывала,
    # потому что эта совпадала раньше и без условий.
    prompt_hint="",
)
