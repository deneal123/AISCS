"""Image generation sub-agent."""

import logging
import re
from collections.abc import AsyncGenerator

from service.domain.capabilities.agent_spec import COST_PAID, AgentSpec
from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import RunExecutionContext, require_execution
from service.domain.subagents.base import BaseSubAgent
from service.domain.subagents.utils import pick_image_model, pick_meta_model
from service.domain.usage_ledger import UsageKind
from service.domain.usage_tracking import build_token_usage_meta
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext

logger = logging.getLogger(__name__)

# Маркеры ПРАВКИ предыдущей картинки: только при них применяем reference (image-to-image).
# ⚠️ Наличие картинки в треде само по себе НЕ повод её редактировать — «нарисуй собаку»
# после «нарисуй кота» должен рисовать заново. Поэтому нужен ЯВНЫЙ сигнал, что речь о той
# же картинке: либо глагол переделки, либо ссылка на «эту/предыдущую» картинку.
_EDIT_MARKERS = re.compile(
    r"(перегенер|перерисуй|переделай|измени|поменяй|замени|сделай\s+(её|ее|его|фон|цвет)"
    r"|другим\s+цветом|тот\s+же|ту\s+же|эту\s+картинк|это\s+изображени|на\s+картинке"
    r"|на\s+фото|тем\s+же|regenerat|re-?generate|edit\s+(this|the|it)|same\s+(image|but)"
    r"|recolor|change\s+the|make\s+(it|the|her|his)|this\s+(image|picture|photo))",
    re.IGNORECASE,
)


def _failure_line(image_model: str, reason: dict) -> str:
    """Первая строка ответа при неудаче: ЧТО случилось и что за это не взяли.

    🔴 Раньше здесь было только «Не удалось сгенерировать изображение». Пользователь
    видел стену промпта, счёт в несколько десятков кредитов и не мог понять ни причины,
    ни того, за что заплатил. Причину провайдер обычно называет сам — она единственный
    след произошедшего; про деньги сказать обязаны мы, потому что «подозрительно дёшево»
    без объяснения читается как ошибка тарификации, а не как «картинки нет — платы нет».
    """
    head = f"Не удалось сгенерировать изображение (модель: {image_model})."
    if reason.get("finish_reason") in {"content_filter", "safety"}:
        head += " Запрос остановлен фильтром безопасности провайдера."
    return head + " Надбавка за изображение не взята — оплачен только текст."


def _looks_like_image_edit(text: str) -> bool:
    """Просит ли пользователь ПРАВКУ предыдущей картинки (а не новую с нуля)."""
    return bool(_EDIT_MARKERS.search(text or ""))


def _condense_usage_event(
    execution: RunExecutionContext,
    cursor: int,
    agent_name: str,
) -> AgentEvent | None:
    projection = execution.usage.project_kinds_since(
        cursor,
        {UsageKind.QUERY_RESOLUTION, UsageKind.IMAGE_CONDENSE},
    )
    metadata = build_token_usage_meta(projection)
    if metadata is None:
        return None
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={**metadata, "kind": "image_condense_usage"},
    )


class ImageGenerationAgent(BaseSubAgent):
    """Specialized agent for image generation / fallback prompt synthesis."""

    def __init__(self, model_settings: dict):
        super().__init__(
            name="image_gen",
            instructions=(
                "Генерируй изображения по запросу пользователя; если генерация "
                "недоступна — делай качественный готовый промпт для генератора изображений."
            ),
            model_settings=model_settings,
        )

    async def _build_prompt_fallback(
        self,
        user_input: str,
        models: list[str],
        execution: RunExecutionContext | None = None,
    ) -> str:
        from service.domain.client import create_chat_completion

        # 🔴 МОДЕЛЬ ПОЛЬЗОВАТЕЛЯ, а не произвольный дешёвый дефолт. Этот текст — то, что
        # человек ЧИТАЕТ вместо картинки, и написан он должен быть выбранной моделью.
        # Живая жалоба: «выбрал модель, а отвечает другая»; `pick_meta_model` для того и
        # заведён, но здесь его не звали, и выбор игнорировался молча.
        text_model = pick_meta_model(models, self.preferred_model())
        if not text_model:
            return ""

        result = await invoke_model_call(
            create_chat_completion,
            kind=UsageKind.IMAGE_CONDENSE,
            execution=require_execution(execution),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Пользователь хочет сгенерировать изображение, но прямой API "
                        "генерации недоступен. Сформируй ОДИН качественный англоязычный "
                        "промпт для SDXL / Flux / DALL-E. Сделай его детальным и "
                        "управляемым: subject, scene, composition, lighting, style, mood, "
                        "camera/lens, colors, details. Добавь негативный промпт (что "
                        "исключить) и краткие рекомендации по вариациям. Выведи результат "
                        "в Markdown-блоках: 'Промпт', 'Негативный промпт', 'Быстрые вариации'."
                    ),
                },
                {"role": "user", "content": user_input},
            ],
            model=text_model,
            temperature=0.7,
            max_tokens=500,
        )
        resp = result.response
        return first_message_content(resp)

    async def _generate_image_b64(
        self,
        image_model: str,
        user_input: str,
        execution: RunExecutionContext | None = None,
        reference_image_url: str | None = None,
        reason_out: dict | None = None,
    ) -> str:
        """Сгенерировать изображение и вернуть base64 PNG (без префикса data:).

        ⚠️ Тело переехало в `tools/image_gen.py` и НЕ продублировано: картинки нужны ещё
        и генератору презентаций, а две копии логики адресации провайдера разошлись бы
        молча — у одного пути картинки работали бы, у другого нет. Метод оставлен как
        тонкий шим: на него завязаны тесты и точки патчинга.

        ``reference_image_url`` — если задан, редактируем эту картинку (image-to-image),
        а не рисуем с нуля: follow-up вида «перегенерируй с другим цветом волос».
        """
        from service.domain.tools.image_gen import generate_image_b64

        return await generate_image_b64(
            image_model,
            user_input,
            reference_image_url=reference_image_url,
            reason_out=reason_out,
            execution=require_execution(execution),
        )

    async def process(self, user_input: str, context: UserContext) -> AsyncGenerator[AgentEvent]:
        yield self.start_event("Запускаю генерацию изображения")

        safety = await self.evaluate_input_safety(user_input)
        if safety["sensitive"]:
            yield AgentEvent(
                type=EventType.STATUS_UPDATE,
                agent_name=self.name,
                data="⚠️ Чувствительная тема: включён безопасный режим генерации.",
                metadata=safety["meta"],
            )
        if safety["blocked"]:
            yield AgentEvent(
                type=EventType.ERROR,
                agent_name=self.name,
                data=safety["message"],
                metadata=safety["meta"],
            )
            yield self.complete_event("Генерация изображения остановлена guardrails")
            return

        # Follow-up condensation and image generation keep separate ledger ranges.
        execution = require_execution()
        condense_cursor = execution.usage.cursor()
        image_generated = False
        image_model: str | None = None
        try:
            from service.domain.client import list_qualified_models
            from service.domain.client.provider_operations import ProviderOperation
            from service.domain.subagents.context_query import (
                build_standalone_query,
            )

            chat_models = await list_qualified_models()
            request = await build_standalone_query(
                user_input,
                context,
                pick_meta_model(chat_models, self.preferred_model()),
                execution=execution,
            )
            if execution.provider_admission is not None:
                image_admission = execution.provider_admission.admit_first(
                    operation=ProviderOperation.IMAGE_OUTPUT,
                    pick_model=lambda models, _prefer: models[0] if models else None,
                )
                image_model = image_admission.model if image_admission is not None else None
            else:
                from service.domain.client.provider_compat import list_inventory_models

                image_model = pick_image_model(await list_inventory_models())

            # Референс для image-to-image: последняя картинка треда, подтянутая backend'ом.
            # Применяем ЕГО только когда текст просит именно ПРАВКУ («перегенерируй с другим
            # цветом волос», «сделай фон темнее»). Иначе — новая генерация с нуля, даже если
            # в треде уже есть картинка: «нарисуй собаку» после «нарисуй кота» не должен
            # редактировать кота. Эвристику применяем к ИСХОДНОМУ user_input, до раскрытия
            # (build_standalone_query переписывает его в самостоятельное описание и маркеры
            # правки могут исчезнуть).
            thread_image = getattr(context, "reference_image_url", None)
            reference_image_url = thread_image if _looks_like_image_edit(user_input) else None

            if image_model:
                edit_mode = bool(reference_image_url)
                yield AgentEvent(
                    type=EventType.TOOL_CALL_START,
                    agent_name=self.name,
                    data=(
                        f"Редактирую изображение моделью {image_model}"
                        if edit_mode
                        else f"Генерирую изображение моделью {image_model}"
                    ),
                )

                b64 = ""
                gen_reason: dict = {}
                try:
                    b64 = await self._generate_image_b64(
                        image_model,
                        request,
                        reference_image_url=reference_image_url,
                        reason_out=gen_reason,
                        execution=execution,
                    )
                except Exception:
                    logger.warning("Image generation failed code=internal")
                    gen_reason["failure_code"] = "internal"
                image_generated = bool(b64)

                if b64:
                    # b64_json → пайплайн сохранит картинку в стор и подставит
                    # file_url (фронт отрисует MessageArtifact), а тяжёлый inline-блоб
                    # вырежется из метадаты после персиста.
                    yield await self.stream_text_event(
                        "Готово — изображение сгенерировано.",
                        metadata={"b64_json": b64, "model": image_model},
                    )
                else:
                    # Генерация не удалась → отдаём качественный промпт как фолбэк.
                    prompt_fallback = ""
                    try:
                        prompt_fallback = await self._build_prompt_fallback(
                            request, chat_models, execution=execution
                        )
                    except Exception:
                        logger.debug("Prompt fallback generation failed code=internal")

                    if prompt_fallback.strip():
                        async for chunk_event in self.stream_text_chunks(
                            (
                                f"{_failure_line(image_model, gen_reason)}\n\n"
                                "Ниже — готовый промпт для генератора изображений:\n\n"
                                f"{prompt_fallback}"
                            ),
                            metadata={"fallback": "prompt_only", "model": image_model},
                        ):
                            yield chunk_event
                    else:
                        yield await self.stream_text_event(
                            f"{_failure_line(image_model, gen_reason)} "
                            "Попробуйте позже или опишите запрос иначе."
                        )
            else:
                reply = await self._build_prompt_fallback(request, chat_models, execution=execution)
                if reply.strip():
                    async for chunk_event in self.stream_text_chunks(reply):
                        yield chunk_event
        except Exception:
            logger.error("Image generation failed code=internal")
            yield self.error_event("Генерация изображения завершилась безопасной ошибкой.")

        # Раскрытие follow-up — отдельный ТЕКСТОВЫЙ вызов: тарифицируем его своей
        # моделью и ОТДЕЛЬНЫМ событием, чтобы он не подменял модель/цену картинки
        # (аудит B5). reply_assembler.consume суммирует его как любой usage.
        if usage_event := _condense_usage_event(execution, condense_cursor, self.name):
            yield usage_event

        # token_usage в AGENT_COMPLETE — иначе reply_assembler не начислит кредиты
        # за генерацию (раньше картинки были бесплатны). Если провайдер не вернул
        # usage, но картинка сгенерирована — начисляем фикс-эквивалент за изображение.
        yield self.complete_event(
            "Генерация изображения завершена",
            self._usage_meta(
                execution.usage.project_kind_since(condense_cursor, None),
                image_generated,
                model=image_model,
            ),
        )

    @staticmethod
    def _usage_meta(usage: dict, image_generated: bool, model: str | None = None) -> dict | None:
        """Реальный usage провайдера; иначе (картинка есть, но usage пуст) —
        фикс-эквивалент за изображение, чтобы генерация не была бесплатной."""
        meta = build_token_usage_meta(usage)
        if meta is not None:
            return meta
        if image_generated:
            # Провайдер не отдал usage по image-модальности → фикс-эквивалент
            # (≈ стоимость одного изображения в токенах), помечаем estimated.
            # model ОБЯЗАТЕЛЕН: без него resolve_model_price(None) уходит в ДЕФОЛТ-цену
            # вместо цены image-модели (аудит P1.5) — картинка тарифилась по чужому тарифу.
            return {
                "token_usage": {
                    "prompt": 0,
                    "completion": 1024,
                    "total": 1024,
                    "model": model,
                    "estimated": True,
                }
            }
        return None


SPEC = AgentSpec(
    name="image_gen",
    label_ru="генерация изображения",
    build=ImageGenerationAgent,
    billing_name="image_gen",
    cost_class=COST_PAID,
    prompt_hint="просят нарисовать, сгенерировать картинку, иллюстрацию.",
)
