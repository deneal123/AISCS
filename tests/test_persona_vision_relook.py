"""Персонный пере-просмотр пикселей: три гейта и ЦЕНА.

Это единственная ветка личностей, которая добавляет ПЛАТНЫЙ вызов провайдера. Поэтому
здесь проверяется не «работает ли», а «когда именно срабатывает и учтён ли счёт».
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from service.domain import persona
from service.domain.persona.lens import PersonaLens
from service.domain.persona.schema import PersonaSpec
from service.domain.pipeline import multimodal as mm
from service.schemas.agents import ModalityAttachment

FOCUS = "МАРКЕР-ЗРЕНИЕ: читай символику расклада"
RELOOK_TEXT = "Три карты: Шут, Башня, Звезда — прямое положение."

TAROT = PersonaSpec(
    id="tarot", label="Таролог", core={"identity": "Символы."}, slots={"vision": FOCUS}
)
NO_VISION = PersonaSpec(
    id="analyst", label="Аналитик", core={"identity": "Считаю."}, slots={"analyst.image": "числа"}
)


@pytest.fixture
def vlm(monkeypatch):
    """Считает вызовы VLM и запоминает переданный угол зрения."""
    calls: list[dict] = []

    async def _describe(data, content_type, name, *, focus="", execution=None):
        calls.append({"focus": focus, "bytes": len(data)})
        if execution is not None:
            execution.usage.record_usage(
                {"prompt": 100}, model="vision-test", kind="multimodal_usage"
            )
        return RELOOK_TEXT

    async def _get(url):
        return SimpleNamespace(status_code=200, content=b"x" * 100, headers={})

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return await _get(url)

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client())
    import service.domain.media as media_mod

    monkeypatch.setattr(media_mod, "describe_image", _describe)
    return calls


def _img(url: str | None = "https://storage/img.png") -> ModalityAttachment:
    return ModalityAttachment(
        kind="image", name="p.png", content="нейтральное описание", source_url=url
    )


@pytest.mark.asyncio
async def test_relook_happens_only_with_vision_slot(vlm):
    """🔴 ЦЕНА: без слота `vision` — НИ ОДНОГО лишнего вызова VLM."""
    usage: dict = {}

    with persona.use_persona(PersonaLens([NO_VISION])):
        out = await mm._content_for_persona(_img(), usage)

    assert vlm == [], "пере-просмотр случился без слота — каждая картинка подорожала вдвое"
    assert out == "нейтральное описание"
    assert not usage


@pytest.mark.asyncio
async def test_no_persona_means_no_relook(vlm):
    usage: dict = {}

    assert await mm._content_for_persona(_img(), usage) == "нейтральное описание"
    assert vlm == []


@pytest.mark.asyncio
async def test_relook_adds_persona_view_and_keeps_neutral(vlm):
    """Со слотом: угол зрения уходит в VLM, нейтральное описание СОХРАНЯЕТСЯ."""
    usage: dict = {}

    with persona.use_persona(PersonaLens([TAROT])):
        out = await mm._content_for_persona(_img(), usage)

    assert len(vlm) == 1 and vlm[0]["focus"] == FOCUS
    assert "нейтральное описание" in out, "нейтральное описание затёрто — сломается follow-up"
    assert RELOOK_TEXT in out


@pytest.mark.asyncio
async def test_relook_is_billed(vlm):
    """🔴 Второй платный вызов обязан попасть в счёт.

    Этот класс дыр в проекте находили трижды (веер аналитиков был бесплатным, мета-вызовы
    шли мимо биллинга, надбавка бралась за непроизведённый артефакт).
    """
    from service.domain.run_context import require_execution

    execution = require_execution()
    cursor = execution.usage.cursor()

    with persona.use_persona(PersonaLens([TAROT])):
        await mm._content_for_persona(_img(), execution)

    usage = execution.usage.project_since(cursor)
    assert usage.get("prompt"), "пере-просмотр не учтён — платформа платит, счёта нет"


@pytest.mark.asyncio
async def test_without_source_url_relook_is_skipped(vlm):
    """Старые треды и вложения без ссылки не должны падать — просто нет пере-просмотра."""
    usage: dict = {}

    with persona.use_persona(PersonaLens([TAROT])):
        out = await mm._content_for_persona(_img(url=None), usage)

    assert vlm == []
    assert out == "нейтральное описание"


@pytest.mark.asyncio
async def test_non_image_modality_is_untouched(vlm):
    usage: dict = {}
    audio = ModalityAttachment(kind="audio", name="a.wav", content="транскрипт", source_url="u")

    with persona.use_persona(PersonaLens([TAROT])):
        assert await mm._content_for_persona(audio, usage) == "транскрипт"
    assert vlm == []


@pytest.mark.asyncio
async def test_download_failure_degrades_to_neutral(monkeypatch, vlm):
    """Протухшая ссылка → работаем по нейтральному описанию, а не роняем анализ."""

    class _Broken:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            raise RuntimeError("ссылка протухла")

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Broken())
    usage: dict = {}

    with persona.use_persona(PersonaLens([TAROT])):
        out = await mm._content_for_persona(_img(), usage)

    assert out == "нейтральное описание"
    assert vlm == []
