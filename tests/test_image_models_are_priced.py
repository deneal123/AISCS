"""Картиночная модель не может тарифицироваться как дешёвая текстовая.

🔴 Замер по живому каталогу провайдера: выходной токен `google/gemini-2.5-flash-image`
стоит 3.04 ₽/1k, а `gemini-3-pro-image` — 12.17 ₽/1k. При этом классификатор относил их
к `fast` (0.06 ₽/1k): недобор в 51 и 203 раза соответственно. Держалось всё на
фиксированной надбавке за инструмент — числе, никак не связанном с моделью. Смена
картиночной модели на более дорогую превратила бы генерацию в прямой убыток, и ни один
тест этого не заметил бы: ошибок нет, счёт выставляется, просто не тот.

Причина классификации отдельная и своя: «mini» находилось ВНУТРИ «geMINI», из-за чего
весь флагманский Gemini уезжал в самый дешёвый класс, а ветка `gemini` в `_LARGE_RE`
была мёртвой — до неё не доходило никогда.
"""

from __future__ import annotations

import pytest

from service.settings import config
from service.shared.model_class import classify_model, cost_rank

# Список ЗЕРКАЛИТ `_PREFERRED_IMAGE_MODELS` сайдкара: именно из него выбирается модель
# генерации, и именно он определяет, что мы реально платим провайдеру.
PREFERRED_IMAGE_MODELS = (
    "google/gemini-2.5-flash-image",
    "google/gemini-3.1-flash-image",
    "google/gemini-3-pro-image",
)


@pytest.mark.parametrize("model", PREFERRED_IMAGE_MODELS)
def test_preferred_image_models_are_classified_as_image(model):
    """🔴 Иначе фолбэк-цена берётся текстовая, и мы платим за картинку из своего кармана."""
    assert classify_model(model) == "image"


def test_image_is_the_most_expensive_class():
    """Ранг решает и подбор модели при фейловере: картинка не должна выглядеть дешёвой."""
    assert cost_rank("google/gemini-2.5-flash-image") > cost_rank("anthropic/claude-opus-4")
    assert cost_rank("anthropic/claude-opus-4") > cost_rank("openai/gpt-4o-mini")


def test_image_fallback_price_covers_the_real_rate():
    """Фолбэк обязан покрывать САМУЮ ДОРОГУЮ картиночную модель из предпочитаемых.

    Он применяется, только когда модели нет в прайс-реестре, — то есть ровно в момент,
    когда мы о ней ничего не знаем. Ошибаться там безопаснее в сторону перебора.
    """
    _, out_price = config.billing.class_prices_rub_per_1k["image"]

    assert out_price >= 12.17, "фолбэк ниже цены gemini-3-pro-image — недобор на каждой картинке"


def test_gemini_flagships_are_not_cheap_class():
    """🔴 «mini» внутри «gemini» уводило весь флагманский Gemini в класс `fast`."""
    for model in ("google/gemini-2.5-pro", "google/gemini-ultra", "google/gemini-1.5-pro"):
        assert classify_model(model) == "large", f"{model} снова тарифится как мелкая модель"


def test_real_mini_models_stay_fast():
    """Обратная сторона: настоящие mini-модели не должны подорожать."""
    for model in ("openai/gpt-4o-mini", "openai/gpt-5-nano", "anthropic/claude-haiku-latest"):
        assert classify_model(model) == "fast"


def test_image_surcharge_is_overhead_not_a_patch():
    """Надбавка покрывает НЕВИДИМОЕ В ТОКЕНАХ, а не цену самой модели.

    Пока она замещала цену модели (5 ₽), тариф не зависел от того, какой моделью рисуем.
    Теперь токены картинки тарифицируются по её настоящей цене, а надбавка — это
    неудачные попытки (за них платим мы) и хранение артефакта.
    """
    surcharge = config.billing.tool_surcharge_rub["image_gen"]

    assert surcharge <= 2.0, (
        "надбавка снова размером с цену модели — значит опять заменяет её, а не дополняет"
    )
