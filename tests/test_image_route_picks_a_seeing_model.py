"""На вопрос о картинке отвечает модель, которая картинку ПРИНИМАЕТ.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Загружена картинка из четырёх цветных четвертей (красный,
зелёный, жёлтый, синий), вопрос — назвать цвет каждой. При `input_type="image"` кандидатами
роутеру шли ВСЕ 411 моделей агрегатора, и он выбрал `aion-labs/aion-rp-llama-3.1-8b` —
roleplay-модель на 8 миллиардов параметров — с обоснованием «Модель подходит для анализа
изображений». Ответ, три прогона подряд:

    Верх-лево: зеленовато-голубой; Верх-право: красновато-оранжевый;
    Низ-лево: тёмно-синий; …

Ни одного попадания. Зрение в тех прогонах отказало (ключ провайдера исчерпан), в контексте
лежала прямая заглушка «рассмотреть НЕ УДАЛОСЬ: не описывай и не угадывай» — и модель всё
равно выдала выдумку как факт. Выдуманное описание СВОЕЙ картинки человек проверить не
может, поэтому оно хуже честного отказа.

⚠️ Причина была записана в коде как осознанное решение: для text кандидаты сужались до
курируемого шорт-листа («иначе LLM-роутер выбирает экзотику, которая падает по timeout»), а
для image/audio/video отдавался полный список — «там своя семья моделей». Для аудио и видео
это верно (ASR и генераторы), а для картинки семья определяется НЕ именем, а способностью
принять изображение.

⚠️ ПО КАТАЛОГУ, А НЕ ПО ИМЕНИ: отбор по подстроке уже проверялся замером и провалился — 10
незрячих среди совпавших и 160 зрячих мимо.
"""

from __future__ import annotations

import pytest

from service.domain.tools import router


@pytest.fixture
def catalog(monkeypatch):
    """Каталог, где зрение объявлено ПРИЗНАКОМ, а не намёком в имени."""
    seeing = {"openai/gpt-4o", "google/gemini-2.5-flash"}

    async def _catalog():
        return {"data": []}

    def _has(model, capability, cat):
        return capability == "vision" and model in seeing

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr("service.shared.model_catalog.model_has_capability", _has)
    return seeing


MODELS = [
    "aion-labs/aion-rp-llama-3.1-8b",  # roleplay, зрения нет — та самая из замера
    "openai/gpt-4o",
    "some/coder-large",
    "google/gemini-2.5-flash",
]


@pytest.mark.asyncio
async def test_only_seeing_models_are_offered_for_an_image(catalog):
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: незрячая roleplay-модель выбыла."""
    candidates = await router._constrain_to_seeing(MODELS)

    assert "aion-labs/aion-rp-llama-3.1-8b" not in candidates
    assert set(candidates) == {"openai/gpt-4o", "google/gemini-2.5-flash"}


@pytest.mark.asyncio
async def test_a_name_that_merely_sounds_visual_is_not_enough(catalog, monkeypatch):
    """🔴 ГРАНИЦА, НА КОТОРОЙ ПРОЕКТ УЖЕ ОБЖИГАЛСЯ. `vision` в имени — не способность:
    замер дал 10 незрячих среди совпавших по имени. Решает каталог."""
    candidates = await router._constrain_to_seeing(["fake/vision-llama", "openai/gpt-4o"])

    assert candidates == ["openai/gpt-4o"]


@pytest.mark.asyncio
async def test_without_any_seeing_model_the_list_is_unchanged(monkeypatch):
    """🔴 ГРАНИЦА С ДРУГОЙ СТОРОНЫ. Зрячих нет вовсе — пустой список кандидатов оставил бы
    человека без ответа. Рискованный выбор лучше пустого."""

    async def _catalog():
        return {"data": []}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability", lambda m, c, cat: False
    )

    assert await router._constrain_to_seeing(MODELS) == MODELS


@pytest.mark.asyncio
async def test_a_broken_catalog_does_not_break_routing(monkeypatch):
    """⚠️ Каталог — внешний источник, и он падал уже не раз. Его сбой обязан оставлять
    прежнее поведение, а не ронять маршрутизацию."""

    async def _boom():
        raise RuntimeError("каталог недоступен")

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _boom)

    assert await router._constrain_to_seeing(MODELS) == MODELS


@pytest.mark.asyncio
async def test_text_and_audio_are_not_touched(catalog, monkeypatch):
    """🔴 ТОЧКА ВЫЗОВА И ЕЁ ГРАНИЦЫ. Сужение по зрению применяется ТОЛЬКО к картинке:
    для аудио оно отрезало бы ASR-семью, для текста — заменило бы курируемый шорт-лист.
    """
    seen: dict = {}

    async def _seeing(models):
        seen["image"] = True
        return models

    monkeypatch.setattr(router, "_constrain_to_seeing", _seeing)
    monkeypatch.setattr(router, "_constrain_candidates", lambda models: models[:1])

    async def _route(input_type):
        seen.clear()
        try:
            await router.route_model(text="что тут", selected_model=None, input_type=input_type)
        except Exception:  # noqa: BLE001 — провайдеров в тесте нет, важен сам отбор
            pass
        return dict(seen)

    # 🔴 И ГЛАВНОЕ — ЧТО ДЛЯ КАРТИНКИ ОТБОР ВСЁ-ТАКИ ПРИМЕНЯЕТСЯ. Без этой строки правило
    # проверялось «в вакууме»: мутация «для картинки снова все модели» прошла ЗЕЛЁНОЙ,
    # потому что тесты держали функцию, а не место, где её зовут.
    assert await _route("image") == {"image": True}, "картинку не сузили по зрению"
    assert await _route("audio") == {}, "аудио сузили по зрению — ASR-семья отрезана"
    assert await _route("text") == {}, "текст сузили по зрению вместо шорт-листа"


# --- фейловер не теряет зрение ------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_the_substitute_of_a_seeing_model_also_sees(monkeypatch):
    """🔴 ВТОРОЙ СЛОЙ ТОГО ЖЕ ДЕФЕКТА, И ИМЕННО ОН СРАБОТАЛ В ЗАМЕРЕ. Роутер выбрал
    зрячую `openai/gpt-5-image` — правка кандидатов подействовала, — но провайдер её не
    дал, и фейловер увёл на `aion-labs/aion-rp-llama-3.1-8b`: заменитель подбирался по
    ЦЕНЕ и ничего не знал про модальность. Ответ пришёл выдуманный.
    """
    from service.domain.client import registry

    async def _catalog():
        return {"data": []}

    seeing = {"openai/gpt-5-image", "google/gemini-2.5-flash"}
    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability",
        lambda m, c, cat: c == "vision" and m in seeing,
    )

    kept = await registry._keep_same_modality(
        ["aion-labs/aion-rp-llama-3.1-8b", "google/gemini-2.5-flash"], "openai/gpt-5-image"
    )

    assert kept == ["google/gemini-2.5-flash"], "незрячий заменитель снова допустим"


@pytest.mark.asyncio
async def test_a_text_model_keeps_the_whole_pool(monkeypatch):
    """🔴 ГРАНИЦА. Заменяли НЕзрячую модель — сужать не по чему, и сужение здесь означало
    бы отказ от половины провайдеров ради требования, которого никто не предъявлял."""
    from service.domain.client import registry

    async def _catalog():
        return {"data": []}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability", lambda m, c, cat: False
    )

    pool = ["a/one", "b/two"]

    assert await registry._keep_same_modality(pool, "some/text-model") == pool


@pytest.mark.asyncio
async def test_without_a_seeing_substitute_the_pool_is_rejected(monkeypatch):
    """No vision-capable substitute is safer than a fabricated blind answer."""
    from service.domain.client import registry

    async def _catalog():
        return {"data": []}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability",
        lambda m, c, cat: c == "vision" and m == "openai/gpt-5-image",
    )

    pool = ["aion-labs/aion-rp-llama-3.1-8b"]

    assert await registry._keep_same_modality(pool, "openai/gpt-5-image") == []


@pytest.mark.asyncio
async def test_the_failover_applies_explicit_vision_requirement(monkeypatch):
    """The request requirement, rather than a model-name guess, governs failover."""
    from service.domain.client import registry
    from service.domain.client.model_requirements import ModelRequirement

    class _Module:
        @staticmethod
        async def list_available_models():
            return ["b/other", "b/seeing"]

    async def _catalog():
        return {}

    monkeypatch.setattr(registry, "get_provider_module", lambda name: _Module)
    monkeypatch.setattr(
        "service.shared.model_catalog.get_openrouter_catalog",
        _catalog,
    )
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability",
        lambda model, capability, catalog: capability == "vision" and model == "b/seeing",
    )

    selected = await registry.resolve_model_for(
        "openrouter",
        prefer=None,
        requirement=ModelRequirement(vision=True),
    )

    assert selected == "b/seeing"


@pytest.mark.asyncio
async def test_an_image_generator_is_not_offered_as_an_answering_model(monkeypatch):
    """🔴 ВТОРАЯ РЕДАКЦИЯ ПРАВКИ, И ЕЁ ПОТРЕБОВАЛ ЗАМЕР. Каталог честно помечает
    `openai/gpt-5-image` зрячей — она и правда видит, — но словами не отвечает. Роутер её
    выбрал, чат-путь отверг («Blocked non-chat model in chat path»), фейловер увёл на
    незрячую roleplay-модель, и человек снова получил выдуманные цвета.

    Зрение и чат-пригодность — разные свойства, и требуются ОБА.
    """

    async def _catalog():
        return {"data": []}

    monkeypatch.setattr("service.shared.model_catalog.get_openrouter_catalog", _catalog)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_has_capability", lambda m, c, cat: c == "vision"
    )

    kept = await router._constrain_to_seeing(["openai/gpt-5-image", "openai/gpt-4o"])

    assert kept == ["openai/gpt-4o"], "генератор картинок снова предлагается как собеседник"
