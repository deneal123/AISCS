"""Кому показывают ПИКСЕЛИ и что видит модель, когда показать их не удалось.

Это единственное место во всём конвейере, которое смотрит на изображение: дальше
`ModalityAttachment.content` несёт ТЕКСТ. Значит обе ошибки здесь неисправимы ниже по
течению — и неверно выбранная модель, и молчаливая заглушка.

Замер, из которого выросли эти правила (dev-стенд, 2026-07-28): у провайдера 468 моделей,
зрение подтверждено каталогом у 187, а прежний отбор ПО ИМЕНИ давал 37 совпадений — 10 из
них БЕЗ зрения (генераторы картинок, транскрайберы, search-preview), и мимо проходили 160
зрячих (весь Claude, Gemini, Amazon Nova).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from service.domain import media
from service.shared import model_catalog

# Каталог как у живого провайдера по составу: генератор с «image» в имени, транскрайбер с
# «gpt-4o» в имени, зрячая модель, по имени которой о зрении не догадаться, и «первая по
# алфавиту» зрячая — ровно те четыре роли, на которых ломался отбор именем.
#
# ⚠️ ЗРЯЧАЯ МОДЕЛЬ ДЛЯ СРАВНЕНИЙ ВЗЯТА ВНЕ КУРИРУЕМОГО СПИСКА (`amazon/nova-pro-v1`), и
# это не мелочь. Первая редакция тестов сравнивала с `anthropic/claude-haiku-4.5` — а он
# в `_PREFERRED_VLM`, то есть выигрывал ДО проверки зрения. Мутация «считать зрячими всех»
# оставалась зелёной: у теста была вторая причина сработать.
_CATALOG = {
    "openai/gpt-image-1": {"capabilities": [], "context_window": 4096, "name": "gen"},
    "openai/gpt-4o-transcribe": {"capabilities": [], "context_window": 4096, "name": "stt"},
    "baidu/ernie-4.5-vl-424b-a47b": {"capabilities": ["vision"], "context_window": 4096},
    "amazon/nova-pro-v1": {"capabilities": ["vision"], "context_window": 4096},
    "openai/gpt-4o-mini": {"capabilities": ["vision", "tools"], "context_window": 4096},
}


@pytest.fixture
def catalog(monkeypatch):
    """Живой каталог в кэше, чтобы `get_openrouter_catalog` не ходил в сеть."""
    monkeypatch.setitem(model_catalog._cache, "data", dict(_CATALOG))
    monkeypatch.setitem(model_catalog._cache, "ts", time.time())
    return _CATALOG


@pytest.mark.asyncio
async def test_image_generator_never_gets_the_pixels(catalog) -> None:
    """🔴 Генератор картинок — НЕ зрение, хотя в имени стоит `image`.

    Отбор именем ставил `openai/gpt-image-1` первым кандидатом: просьбу описать он
    выполнить не может, и пользователь платил за вызов, возвращающий отказ или картинку.
    """
    picked = await media._pick_vlm(["openai/gpt-image-1", "amazon/nova-pro-v1"])

    assert picked == "amazon/nova-pro-v1"


@pytest.mark.asyncio
async def test_transcriber_named_like_a_vlm_is_not_picked(catalog) -> None:
    """`gpt-4o-transcribe` совпадал с прежним `gpt-4o` в регулярке, а зрения не имеет."""
    picked = await media._pick_vlm(["openai/gpt-4o-transcribe", "amazon/nova-pro-v1"])

    assert picked == "amazon/nova-pro-v1"


@pytest.mark.asyncio
async def test_seeing_model_wins_even_when_its_name_says_nothing(catalog) -> None:
    """⚠️ Проверяем ПРИЧИНУ выбора: зрение подтверждено каталогом, а не именем.

    В имени `amazon/nova-pro-v1` нет ни `vision`, ни `vl`, ни `multimodal` —
    прежний отбор не находил здесь НИЧЕГО и отдавал заглушку, хотя зрячая модель была.
    """
    picked = await media._pick_vlm(["amazon/nova-pro-v1"])

    assert picked == "amazon/nova-pro-v1"


@pytest.mark.asyncio
async def test_curated_preference_beats_the_alphabet(catalog) -> None:
    """Из ДВУХ зрячих берём курируемую, а не первую по списку провайдера.

    На стенде первой оказывалась `baidu/ernie-4.5-vl-424b-a47b` — 424 млрд параметров на
    каждую картинку платформы просто потому, что «b» раньше «o».
    """
    picked = await media._pick_vlm(["baidu/ernie-4.5-vl-424b-a47b", "openai/gpt-4o-mini"])

    assert picked == "openai/gpt-4o-mini"


@pytest.mark.asyncio
async def test_unknown_model_falls_back_to_the_name(catalog) -> None:
    """Модель вне каталога (нативный провайдер) — единственный случай отбора именем."""
    picked = await media._pick_vlm(["some-vendor/custom-vl-7b"])

    assert picked == "some-vendor/custom-vl-7b"


@pytest.mark.asyncio
async def test_unknown_generator_is_not_rescued_by_the_name(catalog) -> None:
    """⚠️ Из фолбэка убраны `image` и `dall-e`: они ловили генераторы."""
    assert await media._pick_vlm(["some-vendor/dall-e-3", "some-vendor/image-gen-2"]) is None


# --------------------------------------------------------------------------- #
# Что видит модель, когда показать пиксели не удалось                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_failure_to_look_is_said_out_loud(catalog, monkeypatch) -> None:
    """🔴 Заглушка ОБЯЗАНА сказать, что картинку не смотрели.

    Прежняя «[Изображение загружено: qr-code.gif]» несла только имя файла, и модель
    разворачивала его в правдоподобный текст: на живом прогоне пришла энциклопедическая
    статья о том, что такое QR-код, — про содержимое ЭТОГО кода ни слова.
    """
    monkeypatch.setattr(media, "list_qualified_models", _no_seeing_models)

    text = await media.describe_image(b"\x89PNG", "image/png", "qr-code.gif")

    assert "qr-code.gif" in text
    assert "НЕ УДАЛОСЬ" in text and "не угадывай" in text


async def _no_seeing_models(*_args) -> list[str]:
    return ["openai/gpt-image-1"]


@pytest.mark.asyncio
async def test_the_chosen_model_is_the_one_actually_called(catalog, monkeypatch) -> None:
    """⚠️ ТОЧКА ВЫЗОВА, а не только функция отбора.

    Правило живёт в двух местах: `_pick_vlm` решает, а `describe_image` обязан звать
    решённое. Мутация, оставляющая отбор нетронутым и подставляющая в запрос другую
    модель, прошла бы мимо тестов выше — в проекте этот класс промаха ловили трижды.
    """
    seen: dict = {}

    async def _models(*_args) -> list[str]:
        return ["openai/gpt-image-1", "openai/gpt-4o-mini"]

    monkeypatch.setattr(media, "list_qualified_models", _models)

    async def _resolve(_model):
        return "openai", _FakeClient(seen)

    monkeypatch.setattr(
        "service.domain.client.provider_compat.resolve_model_client",
        _resolve,
    )

    text = await media.describe_image(b"\x89PNG", "image/png", "a.png")

    assert seen["model"] == "openai/gpt-4o-mini"
    # Описание доезжает целиком, но обрамлённым: ниже по конвейеру пикселей уже нет,
    # и без рамки пересказ выдаётся за наблюдение (см. `frame_description`).
    assert text.endswith("описание")


class _FakeClient:
    def __init__(self, seen: dict) -> None:
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._seen = seen

    async def _create(self, **kwargs):
        self._seen.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="описание"))],
            usage=None,
        )


# --------------------------------------------------------------------------- #
# Описание — это ПЕРЕСКАЗ пикселей, а не сами пиксели                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_description_is_marked_as_a_description(catalog, monkeypatch) -> None:
    """🔴 ЗАМЕР ПО КОДУ. Описание уезжало в промпт как обычный текст вложения.

    Заголовок «## Вложения текущей задачи» (и «### Изображение: photo.png» в веере) ни
    словом не говорит, что это ПЕРЕСКАЗ, сделанный другой моделью. Отвечающая модель
    пикселей не видит вовсе, но по разметке этого не понять — и на «опиши подробно» она
    достраивала книжные полки и мониторы, которых на фото не было.
    """
    seen: dict = {}

    async def _models(*_args) -> list[str]:
        return ["openai/gpt-4o-mini"]

    monkeypatch.setattr(media, "list_qualified_models", _models)

    async def _resolve(_model):
        return "openai", _FakeClient(seen)

    monkeypatch.setattr(
        "service.domain.client.provider_compat.resolve_model_client",
        _resolve,
    )

    text = await media.describe_image(b"\x89PNG", "image/png", "photo.png")

    assert "ОПИСАНИЕ изображения" in text, "пересказ выдаётся за наблюдение"
    assert "не достраивай детали" in text
    assert "описание" in text, "само описание потеряно рамкой"


def test_frame_is_not_applied_twice() -> None:
    """Повторное обрамление удвоило бы оговорку — и съело бы бюджет ни за что."""
    once = media.frame_description("a.png", "текст")
    twice = media.frame_description("a.png", once)

    assert once == twice


def test_empty_description_is_not_framed() -> None:
    """Рамка вокруг пустоты — та же тонкая подпись, из которой следует вымысел."""
    assert media.frame_description("a.png", "   ") == ""


def test_failure_stub_is_not_framed() -> None:
    """Отказ уже говорит всё сам; рамка сверху сделала бы из него «описание»."""
    stub = media._not_examined("a.png", "провайдер не настроен")

    assert media.frame_description("a.png", stub) == stub


def test_fanout_marks_the_image_block() -> None:
    """⚠️ ВТОРОЙ ПУТЬ. В веере блок несёт пересказ АНАЛИТИКА — рамку он мог не повторить."""
    import inspect

    from service.domain.pipeline import multimodal

    src = inspect.getsource(multimodal.run_modality_fanout)
    assert 'att.kind == "image"' in src and "frame_description" in src, (
        "в мультимодальном веере описание снова выдаётся за наблюдение"
    )
