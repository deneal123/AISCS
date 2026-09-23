"""Классификация модели по имени: image | fast | large | None, и порядок цены.

Копия есть у обеих сторон. Регексы здесь — деньги: у backend по ним ФОЛБЭК-ЦЕНА,
когда модели нет в прайс-реестре, у сайдкара — подбор модели при фейловере.
Разъедутся молча — получим неверное ценообразование без единой ошибки.

Ловится общими векторами (`tests/vectors/model_class_vectors.json`, побайтовая
сверка в CI суперпроекта).
"""

from __future__ import annotations

import re

# 🔴 IMAGE ПРОВЕРЯЕТСЯ ПЕРВЫМ, И ЭТО ДЕНЬГИ. Замер по живому каталогу: генерация одной
# картинки `google/gemini-2.5-flash-image` стоит нам 5.39 ₽ (1771 токен по 3.04 ₽/1k),
# а классифицировалась она как `fast` (0.06 ₽/1k) — недобор в 51 раз. У
# `gemini-3-pro-image` (12.17 ₽/1k) недобор был бы 200-кратным. Держалось всё это на
# фиксированной надбавке за инструмент, то есть на числе, не связанном с моделью:
# смена картиночной модели молча превращала бы генерацию в прямой убыток.
_IMAGE_RE = re.compile(
    r"(-image$|-image-|gpt-image|dall-e|flux|sdxl|stable-diffusion|imagen|kandinsky)",
    re.I,
)
# FAST проверяется раньше LARGE, поэтому «...-mini/nano/flash» перебивает семейство ниже
# (напр. gpt-5-nano → fast, gpt-4o-mini → fast). Неопознанное остаётся None → дефолт.
#
# ⚠️ `(?<![a-z])mini` — НЕ придирка. Без лукбехайнда «mini» находилось внутри «geMINI»,
# и ВСЁ семейство Gemini уезжало в самый дешёвый класс: `gemini-2.5-pro`, `gemini-ultra`
# и прочие флагманы тарифицировались как мелкие модели, если их не было в прайс-реестре.
# Заодно это делало ветку `gemini` в `_LARGE_RE` мёртвой — до неё не доходило никогда.
_FAST_RE = re.compile(
    r"(1b|2b|3b|4b|7b|8b|9b|(?<![a-z])mini|small|lite|flash|lightning|fast|nano|micro|tiny"
    r"|haiku|gemma|phi)",
    re.I,
)
# LARGE ловит и размерные токены, и флагманские семейства. Неоднозначное смещаем в
# large намеренно — fallback-цена крупной модели выше, это защищает от недобилла.
_LARGE_RE = re.compile(
    r"(2[0-9]b|3[0-9]b|6[0-9]b|7[0-9]b|9[0-9]b|1[0-9]{2}b|2[0-9]{2}b|3[0-9]{2}b|4[0-9]{2}b|"
    r"6[0-9]{2}b|large|pro|alpha|ultra|max|opus|sonnet|grok|command|deepseek|gemini|"
    r"gpt-4|gpt-5|chatgpt|reasoner|thinking|glm-4|o[134])",
    re.I,
)

# Порядок ДОРОЖАНИЯ. Неопознанное (None) стоит между fast и large: цена ему берётся
# дефолтная, а она выше fast и ниже large. Картинка дороже любого текста — по замеру
# провайдера её выходной токен в 20-80 раз дороже токена крупной текстовой модели.
_COST_RANK: dict[str | None, int] = {"fast": 0, None: 1, "large": 2, "image": 3}


def classify_model(model_id: str) -> str | None:
    if not model_id:
        return None
    if _IMAGE_RE.search(model_id):
        return "image"
    if _FAST_RE.search(model_id):
        return "fast"
    if _LARGE_RE.search(model_id):
        return "large"
    return None


def cost_rank(model_id: str | None) -> int:
    """Ранг дороговизны по имени модели. Больше — дороже."""
    return _COST_RANK[classify_model(str(model_id or ""))]


def is_not_pricier_than(candidate: str, reference: str | None) -> bool:
    """Не дороже ли `candidate`, чем `reference` (по классу).

    Без `reference` (модель не выбрана) ограничивать нечего — подходит любая.
    """
    if not reference:
        return True
    return cost_rank(candidate) <= cost_rank(reference)
