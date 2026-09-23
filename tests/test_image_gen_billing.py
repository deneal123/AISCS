"""Биллинг генерации изображений (аудит B5).

На follow-up («нарисуй это») раскрытие запроса в самостоятельный (build_standalone_query)
делает ТЕКСТОВЫЙ LLM-вызов. Раньше его usage+модель писались в тот же счётчик, что и
картинка, а провайдер image-модальности usage обычно не отдаёт → генерация билась по цене
ТЕКСТ-модели вместо image, а фикс-эквивалент за картинку не срабатывал. Теперь condense
тарифицируется ОТДЕЛЬНЫМ событием, а картинка — своей моделью/фикс-эквивалентом.
"""

from datetime import UTC, datetime

import pytest

from service.domain.subagents.image_generation import ImageGenerationAgent
from service.schemas.agents import UserContext


def _ctx() -> UserContext:
    return UserContext(user_id="u1", request_time=datetime.now(UTC), thread_id="t1")


def _token_usages(events) -> list[dict]:
    return [
        e.metadata["token_usage"] for e in events if e.metadata and e.metadata.get("token_usage")
    ]


@pytest.mark.asyncio
async def test_image_billed_at_image_model_on_followup(monkeypatch):
    agent = ImageGenerationAgent(model_settings={})

    async def _safe(_txt):
        return {"sensitive": False, "blocked": False, "message": "", "meta": {}}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)

    async def _models():
        return ["gpt-4o-mini", "flux-image"]

    monkeypatch.setattr("service.domain.client.list_available_models", _models)
    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)

    # Раскрытие follow-up тратит токены ТЕКСТ-модели (в диалоге есть история).
    async def _condense(user_input, context, text_model, *, execution=None):
        execution.usage.record_usage(
            {"prompt": 50, "completion": 10},
            model=text_model,
            kind="query_resolution",
        )
        return "нарисуй кота, отражающего суть статьи"

    monkeypatch.setattr(
        "service.domain.subagents.context_query.build_standalone_query",
        _condense,
    )

    # Провайдер image-модальности отдал картинку, но usage НЕ вернул (частый случай).
    async def _gen(image_model, request, execution=None, reference_image_url=None, reason_out=None):
        return "aGVsbG8="  # непустой b64 → картинка «сгенерирована»

    monkeypatch.setattr(agent, "_generate_image_b64", _gen)

    events = [e async for e in agent.process("нарисуй это", _ctx())]
    usages = _token_usages(events)

    # Ровно два начисления: раскрытие (текст-модель) + картинка (image-модель).
    assert len(usages) == 2, "должны биллиться и condense, и генерация — раздельно"

    image_tu = next((u for u in usages if u.get("estimated")), None)
    assert image_tu is not None, "картинка без usage провайдера → фикс-эквивалент (аудит B5)"
    assert image_tu["model"] == "flux-image", (
        "генерация тарифится по image-модели, а не по текст-модели раскрытия"
    )
    assert image_tu["completion"] == 1024  # фикс-эквивалент за изображение

    condense_tu = next((u for u in usages if not u.get("estimated")), None)
    assert condense_tu is not None
    assert condense_tu["model"] == "gpt-4o-mini" and condense_tu["prompt"] == 50


@pytest.mark.asyncio
async def test_image_provider_usage_wins_over_fixed_equivalent(monkeypatch):
    """Если провайдер image ВЕРНУЛ usage — биллим его (по image-модели), не фикс-эквивалент."""
    agent = ImageGenerationAgent(model_settings={})

    async def _safe(_txt):
        return {"sensitive": False, "blocked": False, "message": "", "meta": {}}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)

    async def _models():
        return ["gpt-4o-mini", "flux-image"]

    monkeypatch.setattr("service.domain.client.list_available_models", _models)
    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)

    async def _condense(user_input, context, text_model, *, execution=None):
        return "нарисуй кота"  # первый запрос, без истории → condense usage пуст

    monkeypatch.setattr(
        "service.domain.subagents.context_query.build_standalone_query",
        _condense,
    )

    async def _gen(image_model, request, execution=None, reference_image_url=None, reason_out=None):
        if execution is not None:
            execution.usage.record_usage({"prompt": 12, "completion": 200}, model=image_model)
        return "aGVsbG8="

    monkeypatch.setattr(agent, "_generate_image_b64", _gen)

    events = [e async for e in agent.process("нарисуй кота", _ctx())]
    usages = _token_usages(events)

    assert len(usages) == 1  # condense пуст → только генерация
    assert usages[0]["model"] == "flux-image"
    assert usages[0]["completion"] == 200 and not usages[0].get("estimated")
