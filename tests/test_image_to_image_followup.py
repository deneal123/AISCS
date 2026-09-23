"""Follow-up-правка редактирует предыдущую картинку, новая генерация — рисует с нуля.

Пользователь: «изобрази Елизавету Смирнову» → картинка. Затем «перегенерируй с другим
цветом волос» — это ПРАВКА той же картинки (image-to-image), а не рисунок с нуля.
Провайдер (gemini-2.5-flash-image) это умеет: картинка-референс + инструкция → изменённое
изображение.

⚠️ Ключевой инвариант: наличие картинки в треде НЕ означает, что запрос — правка.
«нарисуй собаку» после «нарисуй кота» должен рисовать заново, а не перекрашивать кота.
Референс применяется ТОЛЬКО когда текст просит именно правку — иначе новый сюжет
редактировался бы поверх старого.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.domain.subagents.image_generation import (
    ImageGenerationAgent,
    _looks_like_image_edit,
)
from service.domain.tools import image_gen
from service.schemas.agents import UserContext


@pytest.mark.parametrize(
    "text",
    [
        "перегенерируй с другим цветом волос",
        "сделай фон темнее",
        "измени цвет платья на красный",
        "поменяй причёску на этой картинке",
        "тот же кот, но зимой",
        "regenerate with blue background",
        "make it brighter",
        "change the hair color",
    ],
)
def test_edit_requests_are_detected(text):
    assert _looks_like_image_edit(text), f"правка не распознана: {text!r}"


@pytest.mark.parametrize(
    "text",
    [
        "нарисуй собаку",
        "изобрази закат над морем",
        "создай логотип для кофейни",
        "сгенерируй портрет девушки",
    ],
)
def test_new_generation_is_not_an_edit(text):
    assert not _looks_like_image_edit(text), (
        f"новая генерация принята за правку — отредактирует прошлую картинку: {text!r}"
    )


def _ctx(reference_image_url=None) -> UserContext:
    return UserContext(
        user_id="u1",
        request_time=datetime.now(UTC),
        thread_id="t1",
        reference_image_url=reference_image_url,
    )


@pytest.fixture
def capture_reference(monkeypatch):
    """Перехватываем, с каким reference ушёл вызов генерации."""
    seen: dict = {}

    async def _gen(image_model, prompt, execution=None, reference_image_url=None, reason_out=None):
        seen["reference"] = reference_image_url
        return "aGVsbG8="  # непустой b64 → «картинка есть»

    monkeypatch.setattr(image_gen, "generate_image_b64", _gen)
    return seen


async def _run(agent, text, ctx):
    events = []
    async for e in agent.process(text, ctx):
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_edit_followup_passes_reference(capture_reference, monkeypatch):
    """⚠️ ГЛАВНОЕ. Правка + картинка в треде → генерация получает референс."""
    agent = ImageGenerationAgent(model_settings={})

    async def _safe(_t):
        return {"sensitive": False, "blocked": False, "message": "", "meta": {}}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)

    async def _models():
        return ["gpt-4o-mini", "google/gemini-2.5-flash-image"]

    monkeypatch.setattr("service.domain.client.list_available_models", _models)
    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)

    async def _condense(user_input, context, text_model, *, execution=None):
        return "portrait with purple hair"

    monkeypatch.setattr("service.domain.subagents.context_query.build_standalone_query", _condense)

    await _run(agent, "перегенерируй с фиолетовыми волосами", _ctx("https://s3/prev.png"))

    assert capture_reference["reference"] == "https://s3/prev.png", (
        "правка не получила референс — картинка сгенерируется с нуля, а не отредактируется"
    )


@pytest.mark.asyncio
async def test_new_generation_ignores_thread_image(capture_reference, monkeypatch):
    """⚠️ Новая генерация НЕ редактирует прошлую картинку, даже если она в треде."""
    agent = ImageGenerationAgent(model_settings={})

    async def _safe(_t):
        return {"sensitive": False, "blocked": False, "message": "", "meta": {}}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)

    async def _models():
        return ["gpt-4o-mini", "google/gemini-2.5-flash-image"]

    monkeypatch.setattr("service.domain.client.list_available_models", _models)
    monkeypatch.setattr("service.domain.client.list_qualified_models", _models)

    async def _condense(user_input, context, text_model, *, execution=None):
        return "a dog"

    monkeypatch.setattr("service.domain.subagents.context_query.build_standalone_query", _condense)

    await _run(agent, "нарисуй собаку", _ctx("https://s3/cat.png"))

    assert capture_reference["reference"] is None, (
        "новая генерация получила референс прошлой картинки — нарисует собаку поверх кота"
    )


@pytest.mark.asyncio
async def test_generate_image_b64_sends_reference_as_multimodal(monkeypatch):
    """Ядро: reference_image_url уходит картинкой в multimodal-сообщении провайдеру."""
    seen: dict = {}

    class _Client:
        def __init__(self):
            self.chat = type("C", (), {"completions": self})()

        async def create(self, **kwargs):
            seen["messages"] = kwargs["messages"]

            class _R:
                choices = [
                    type(
                        "Ch",
                        (),
                        {
                            "message": type(
                                "M",
                                (),
                                {
                                    "content": None,
                                    "images": [
                                        {"image_url": {"url": "data:image/png;base64,eA=="}}
                                    ],
                                },
                            )()
                        },
                    )()
                ]
                usage = None

            return _R()

    import service.domain.client as client_mod

    async def _catalog():
        return ([], {})

    monkeypatch.setattr(client_mod, "get_model_catalog", _catalog, raising=False)
    monkeypatch.setattr(client_mod, "get_provider_module", lambda n: None, raising=False)
    monkeypatch.setattr(client_mod, "get_openai_client", lambda: _Client(), raising=False)

    b64 = await image_gen.generate_image_b64(
        "google/gemini-2.5-flash-image",
        "make hair purple",
        {},
        reference_image_url="data:image/png;base64,QQ==",
    )

    assert b64 == "eA=="
    content = seen["messages"][0]["content"]
    assert isinstance(content, list), "reference не привёл к multimodal-сообщению"
    kinds = {part.get("type") for part in content}
    assert kinds == {"text", "image_url"}, f"нет картинки в запросе к провайдеру: {kinds}"
