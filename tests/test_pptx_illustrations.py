"""Презентация с иллюстрациями: оплачена, переживает сбой, не раздувается.

Раньше генератор отдавал «текст на тёмном прямоугольнике»: один LLM-вызов на структуру и
плоская вёрстка без единой картинки. Теперь он просит у image-модели общий фон и до трёх
иллюстраций к ключевым слайдам.

## Три свойства, за которые тут держимся

**Картинки оплачены.** Каждая — отдельный вызов image-модели. Провайдеры image-модальности
обычно НЕ возвращают usage, поэтому без фикс-эквивалента генерации были бы бесплатны:
вызов состоялся, платформа заплатила, счёт нулевой. И тарифицироваться они обязаны СВОЕЙ
моделью — смешай их с текстовой, и всё посчитается по цене той, что записалась последней
(на этом уже обжигался генератор изображений, аудит B5 и P1.5).

**Дек переживает сбой картинок.** Текст слайдов уже сгенерирован и полезен сам по себе;
отдать ошибку вместо файла значило бы выбросить оплаченную работу. Но деградация обязана
быть ВИДНА — иначе «дек без картинок» неотличим от «так и задумано».

**Число картинок ограничено.** Потолок здесь про деньги, а не про вкус: картинка на
каждый слайд превратила бы дек из 10 слайдов в десять генераций при надбавке, рассчитанной
на одну работу.
"""

from __future__ import annotations

import base64
import logging

import pytest

from service.domain.tools import pptx as pptx_tool

# Минимальный валидный PNG 1×1 — нужен настоящий, иначе python-pptx не вставит картинку.
PNG_1X1 = base64.b64encode(
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
).decode()


def _structure(slides: int = 5, with_prompts: int = 3) -> dict:
    out = [{"type": "title", "title": "Тема", "subtitle": "Подзаголовок"}]
    for i in range(slides - 1):
        slide = {"type": "content", "title": f"Слайд {i}", "bullets": ["раз", "два", "три"]}
        if i < with_prompts:
            slide["image_prompt"] = f"illustration {i}"
        out.append(slide)
    return {"title": "Тема", "theme": "deep blue abstract waves", "slides": out}


@pytest.fixture
def image_model(monkeypatch):
    """Доступная image-модель и подконтрольный генератор картинок."""
    calls: list[str] = []

    async def _models():
        return ["img/model", "text/model"]

    async def _gen(model, prompt, *, execution=None, usage_kind=None):
        calls.append(prompt)
        return PNG_1X1

    import service.domain.client as client_mod
    import service.domain.subagents.utils as utils_mod
    import service.domain.tools.image_gen as image_mod

    monkeypatch.setattr(client_mod, "list_available_models", _models)
    monkeypatch.setattr(utils_mod, "pick_image_model", lambda models: "img/model")
    monkeypatch.setattr(image_mod, "generate_image_b64", _gen)
    return calls


# --------------------------------------------------------------------------- #
# Потолок и общая тема                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_illustrations_are_capped(image_model):
    """⚠️ ПОТОЛОК ЭТО ДЕНЬГИ. Даже если модель разметила все слайды."""
    structure = _structure(slides=12, with_prompts=11)

    _, report = await pptx_tool._render_images(structure, None)

    assert report["requested"] == pptx_tool._MAX_ILLUSTRATIONS + 1, (
        f"запрошено {report['requested']} генераций — потолок "
        f"({pptx_tool._MAX_ILLUSTRATIONS} иллюстраций + фон) не соблюдён"
    )


@pytest.mark.asyncio
async def test_cap_holds_without_a_background(image_model):
    """⚠️ И без фона тоже.

    Первая версия считала `len(jobs)`, куда фон уже добавлен, — при пустой теме
    пропускала ЧЕТЫРЕ иллюстрации вместо трёх. «Примерно три» для потолка про деньги
    не годится.
    """
    structure = _structure(slides=12, with_prompts=11)
    structure["theme"] = ""

    _, report = await pptx_tool._render_images(structure, None)

    assert report["requested"] == pptx_tool._MAX_ILLUSTRATIONS


@pytest.mark.asyncio
async def test_theme_is_mixed_into_every_illustration(image_model):
    """Просили ОБЩУЮ тему: без неё слайды выглядят набором случайных картинок."""
    await pptx_tool._render_images(_structure(), None)

    illustrations = [p for p in image_model if p.startswith("illustration")]
    assert illustrations, "иллюстрации не запрашивались — предпосылка неверна"
    assert all("deep blue abstract waves" in p for p in illustrations)


@pytest.mark.asyncio
async def test_prompts_forbid_text_on_images(image_model):
    """Модели рисуют буквы с ошибками — просим их не рисовать вовсе."""
    await pptx_tool._render_images(_structure(), None)

    assert all("no text" in p for p in image_model)


# --------------------------------------------------------------------------- #
# Деньги                                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_images_are_billed_even_without_provider_usage(monkeypatch, image_model):
    """⚠️ ГЛАВНОЕ ПРО ДЕНЬГИ. Провайдер не вернул usage — платит всё равно пользователь.

    Image-модальность обычно не отдаёт usage. Без фикс-эквивалента вызовы бесплатны:
    состоялись, оплачены нами, в счёт не попали.
    """
    from service.domain.subagents.pptx_generation import _image_usage_meta

    meta = _image_usage_meta({"model": "img/model"}, generated=4)

    assert meta is not None, "четыре сгенерированные картинки не попали в счёт"
    usage = meta["token_usage"]
    assert usage["completion"] > 0
    assert usage["model"] == "img/model", (
        "без модели resolve_model_price уходит в ДЕФОЛТ-цену — картинка тарифится по чужому тарифу"
    )
    assert usage.get("estimated") is True, "оценка обязана быть помечена как оценка"


def test_fixed_equivalent_scales_with_count():
    """Четыре картинки не могут стоить как одна."""
    from service.domain.tools.image_gen import fixed_equivalent_usage

    one = fixed_equivalent_usage("img/model", 1)["completion"]
    four = fixed_equivalent_usage("img/model", 4)["completion"]

    assert four == one * 4


def test_nothing_generated_is_not_billed():
    """⚠️ Обратная сторона: не нарисовали — не берём денег."""
    from service.domain.subagents.pptx_generation import _image_usage_meta

    assert _image_usage_meta({"model": "img/model"}, generated=0) is None


# --------------------------------------------------------------------------- #
# Деградация                                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_deck_survives_image_failure(monkeypatch, caplog):
    """⚠️ Картинки не сгенерировались — презентация ВСЁ РАВНО собирается."""

    async def _models():
        return ["img/model"]

    async def _boom(model, prompt, usage_out=None):
        raise ConnectionError("провайдер картинок недоступен")

    import service.domain.client as client_mod
    import service.domain.subagents.utils as utils_mod
    import service.domain.tools.image_gen as image_mod

    monkeypatch.setattr(client_mod, "list_available_models", _models)
    monkeypatch.setattr(utils_mod, "pick_image_model", lambda models: "img/model")
    monkeypatch.setattr(image_mod, "generate_image_b64", _boom)

    with caplog.at_level(logging.WARNING):
        images, report = await pptx_tool._render_images(_structure(), None)

    assert images == {}
    assert report["generated"] == 0 and report["requested"] > 0
    assert any("иллюстрац" in r.message.lower() for r in caplog.records), (
        "сбой генерации не оставил следа в логах"
    )
    # И самое важное: дек всё равно строится.
    assert pptx_tool._build_pptx(_structure(), images), "презентация не собралась без картинок"


@pytest.mark.asyncio
async def test_missing_image_model_is_not_an_error(monkeypatch):
    """У части провайдеров image-модальности нет вовсе — это не сбой."""

    async def _models():
        return ["text/model"]

    import service.domain.client as client_mod
    import service.domain.subagents.utils as utils_mod

    monkeypatch.setattr(client_mod, "list_available_models", _models)
    monkeypatch.setattr(utils_mod, "pick_image_model", lambda models: "")

    images, report = await pptx_tool._render_images(_structure(), None)

    assert images == {}
    assert report["reason"] == "no_image_model"


@pytest.mark.parametrize(
    ("report", "expect"),
    [
        ({"requested": 4, "generated": 4}, ""),
        ({"requested": 4, "generated": 2}, "2 из 4"),
        ({"requested": 4, "generated": 0}, "не удалось"),
        ({"requested": 0, "generated": 0, "reason": "no_image_model"}, "нет модели"),
    ],
    ids=["всё-ок", "частично", "ничего", "модели-нет"],
)
def test_user_is_told_what_happened_with_visuals(report, expect):
    """⚠️ Пользователь узнаёт, что дек вышел беднее задуманного.

    Молча отданная презентация без картинок — деградация, выглядящая как штатная
    работа: файл есть, слайды есть, претензий не сформулировать.
    """
    from service.domain.subagents.pptx_generation import _visual_note

    note = _visual_note(report)
    if expect:
        assert expect in note
    else:
        assert note == "", "штатный случай не должен ничего дописывать"


# --------------------------------------------------------------------------- #
# Вёрстка                                                                       #
# --------------------------------------------------------------------------- #
def test_deck_is_built_with_images():
    """Картинки реально вставляются: файл с ними тяжелее, чем без них."""
    structure = _structure()
    plain = pptx_tool._build_pptx(structure, {})
    rich = pptx_tool._build_pptx(structure, {"background": PNG_1X1, "1": PNG_1X1})

    assert len(rich) > len(plain), "картинки не попали в файл"


def test_broken_image_does_not_break_the_deck(caplog):
    """⚠️ Битая base64 не должна ронять весь дек — текст уже оплачен."""
    with caplog.at_level(logging.WARNING):
        data = pptx_tool._build_pptx(_structure(), {"background": "не-base64", "1": "мусор"})

    assert data, "дек не собрался из-за битой картинки"


def _slide_texts(data: bytes, slide_no: int) -> list[str]:
    """Весь видимый текст слайда — читаем прямо из собранного файла."""
    import io as _io
    import re
    import zipfile

    z = zipfile.ZipFile(_io.BytesIO(data))
    xml = z.read(f"ppt/slides/slide{slide_no}.xml").decode()
    return [t for t in re.findall(r"<a:t>([^<]*)</a:t>", xml) if t.strip()]


def test_closing_slide_keeps_its_bullets():
    """⚠️ РЕГРЕССИЯ, КОТОРУЮ ПРОПУСТИЛИ ВСЕ ОСТАЛЬНЫЕ ПРОВЕРКИ.

    Финальный слайд по промпту — это ВЫВОДЫ и следующие шаги, то есть тезисы, ради
    которых презентацию и открывают в конце. Первая версия вёрстки считала «слайд с
    фоном» синонимом «слайд, свёрстанный как титул», и финал уходил в титульную
    раскладку, где рисуются только заголовок с подзаголовком. Все буллеты пропадали.

    Заметить это по размеру файла или по числу слайдов невозможно: дек собирается, слайд
    на месте, ошибок нет. Поэтому проверка читает ТЕКСТ из собранного pptx.
    """
    structure = {
        "title": "Итоги",
        "theme": "blue",
        "slides": [
            {"type": "title", "title": "Итоги", "subtitle": "Q3"},
            {"type": "content", "title": "Выручка", "bullets": ["рост 18%"]},
            {"type": "content", "title": "Выводы", "bullets": ["масштабировать", "закрыть риск"]},
        ],
    }

    texts = " ".join(_slide_texts(pptx_tool._build_pptx(structure, {}), 3))

    assert "Выводы" in texts
    assert "масштабировать" in texts, "финальный слайд потерял тезисы"
    assert "закрыть риск" in texts


def test_closing_slide_keeps_bullets_with_background_too():
    """И с фоном тоже: именно фон и уводил финал в титульную вёрстку."""
    structure = {
        "title": "Итоги",
        "theme": "blue",
        "slides": [
            {"type": "title", "title": "Итоги", "subtitle": "Q3"},
            {"type": "content", "title": "Выводы", "bullets": ["единственный тезис"]},
        ],
    }

    texts = " ".join(_slide_texts(pptx_tool._build_pptx(structure, {"background": PNG_1X1}), 2))

    assert "единственный тезис" in texts


def test_title_slide_shows_subtitle():
    """Контроль обратной стороны: титул по-прежнему верстается как титул."""
    structure = {
        "title": "Итоги",
        "slides": [{"type": "title", "title": "Итоги", "subtitle": "Третий квартал"}],
    }

    texts = " ".join(_slide_texts(pptx_tool._build_pptx(structure, {}), 1))

    assert "Третий квартал" in texts


def test_prompt_keeps_the_deck_in_the_user_language():
    """⚠️ РЕГРЕССИЯ, НАЙДЕННАЯ ЖИВЫМ ПРОГОНОМ.

    Первая версия промпта говорила «требования к image_prompt и theme: на английском» —
    и модель поняла это как требование ко ВСЕЙ презентации. На русский запрос
    «Сделай презентацию про переход на отечественные LLM-провайдеры» пришёл дек с
    заголовками «Transitioning to Domestic LLM Providers».

    Тест сторожит сам промпт: язык слайдов и язык промптов для картинок должны быть
    разведены явно, иначе модель обобщит требование.
    """
    prompt = pptx_tool._PLAN_PROMPT

    assert "НА ЯЗЫКЕ ЗАПРОСА ПОЛЬЗОВАТЕЛЯ" in prompt, (
        "в промпте не сказано, на каком языке делать слайды — модель уведёт дек "
        "в английский вслед за требованием к image_prompt"
    )
    assert "ТОЛЬКО внутри полей `theme` и `image_prompt`" in prompt, (
        "требование «на английском» не ограничено полями картинок"
    )


def test_image_model_picker_prefers_verified_models():
    """⚠️ Первая подходящая по имени модель НЕ РАБОТАЕТ на нашем транспорте.

    На живом каталоге из 422 моделей регулярка выбирала `black-forest-labs/flux.2-flex` —
    настоящий генератор изображений, который не отвечает на chat/completions с
    `modalities: ["image","text"]` (503, «No endpoints found...»). Проверено перебором:
    из кандидатов работает только семейство `google/gemini-*-image`.
    """
    from service.domain.subagents.utils import pick_image_model

    catalog = [
        "black-forest-labs/flux.2-flex",
        "openai/gpt-image-1-mini",
        "google/gemini-2.5-flash-image",
    ]

    assert pick_image_model(catalog) == "google/gemini-2.5-flash-image", (
        "выбрана модель, не проверенная на нашем транспорте — картинки молча не сгенерируются"
    )


def test_image_model_picker_still_has_a_fallback():
    """У другого провайдера каталог иной: отсутствие выбора хуже неидеального."""
    from service.domain.subagents.utils import pick_image_model

    assert pick_image_model(["some/stable-diffusion-xl"]) == "some/stable-diffusion-xl"
    assert pick_image_model(["only/text-model"]) is None
