"""Оценщик токенов не имеет права ЗАНИЖАТЬ.

🔴 Замер против настоящих токенизаторов (RouterAI/gpt-4o-mini и GigaChat-2-Max) на
корпусе из шести образцов показал, что прежняя модель «латиница 4.0 / кириллица 2.5»
ошибалась в ОБЕ стороны: +51% на русской прозе и −9% на markdown.

Направления ошибки НЕ равнозначны:
* завышение жжёт деньги — сжатие включается там, где текст и так влезал, а одно сжатие
  это до 13 вызовов модели;
* занижение ОПАСНЕЕ — окно модели переполняется, и ответ обрывается на полуслове.

Поэтому формула обязана завышать всегда и умеренно. Эталоны замера лежат в
`tests/vectors/token_estimate_vectors.json` (блок `calibration`) и сверяются побайтово с
копией backend'а — правка коэффициентов не может пройти незаметно.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from service.shared.token_estimate import estimate_tokens

VECTORS = json.loads(
    (pathlib.Path(__file__).parent / "vectors" / "token_estimate_vectors.json").read_text(
        encoding="utf-8"
    )
)

# Тот же корпус, на котором снимался замер. Держим здесь, а не в векторах: в векторах
# лежат ЧИСЛА замера, а тексты нужны только этому тесту.
CORPUS = {
    "проза русская": (
        "Пользователь описывает ситуацию своими словами, довольно подробно и с "
        "оговорками, как это обычно бывает в живой переписке. Он уточняет детали, "
        "возвращается к сказанному ранее и переспрашивает о том, что уже обсуждали."
    )
    * 3,
    "проза техническая": (
        "Функция сборки контекста делит бюджет между секциями по весам, перенормируя их "
        "по присутствующим секциям. Вложения имеют приоритет выше истории и памяти, "
        "поэтому при нехватке места первой сжимается именно история диалога."
    )
    * 3,
    "проза английская": (
        "The assembler splits a single budget across context sections, renormalising "
        "weights over the sections that are actually present in this request, so that "
        "attachments outrank conversation history when the window gets tight."
    )
    * 3,
    "код python": (
        "def compress_to_budget(raw, target, kind='files', usage_out=None):\n"
        "    text = str(raw or '').strip()\n"
        "    if not text or target <= 0:\n"
        "        return ''\n"
        "    if estimate_tokens(text) <= target:\n"
        "        return text\n"
        "    chunks = _split(text, _CHUNK_TOKENS)\n"
        "    return await _map_chunks(chunks, target, kind, usage_out, model)\n"
    )
    * 3,
    "markdown с таблицей": (
        "## Контекст\n\n- facts — факты о пользователе\n- files — вложения задачи\n"
        "- history — свежие реплики диалога\n\n| секция | вес |\n|---|---|\n"
        "| files | 0.35 |\n| history | 0.30 |\n\n> Вложения важнее истории.\n\n"
    )
    * 3,
    "смешанный": (
        "В модуле context_assembler функция _fit режет секцию по бюджету, а "
        "compress_to_budget сжимает её map-reduce через LLM, если секция входит в "
        "COMPRESSIBLE. Порог берётся из compaction_threshold админ-настройки.\n"
    )
    * 3,
}

CALIBRATION = {c["kind"]: c for c in VECTORS["calibration"]["cases"]}


@pytest.mark.parametrize("kind", sorted(CORPUS))
def test_corpus_matches_the_measured_sample(kind):
    """Текст образца не разъехался с числами замера — иначе коридор проверял бы не то."""
    assert len(CORPUS[kind]) == CALIBRATION[kind]["chars"]


@pytest.mark.parametrize("kind", sorted(CORPUS))
def test_estimate_never_underestimates(kind):
    """🔴 ГЛАВНОЕ: занижение переполняет окно модели и обрывает ответ."""
    real_min = CALIBRATION[kind]["real_min"]

    assert estimate_tokens(CORPUS[kind]) >= real_min, (
        f"«{kind}»: оценка ниже реального числа токенов — контекст соберётся больше окна"
    )


@pytest.mark.parametrize("kind", sorted(CORPUS))
def test_estimate_does_not_overestimate_wildly(kind):
    """Завышение — деньги: лишнее сжатие это до 13 вызовов модели."""
    real_min = CALIBRATION[kind]["real_min"]

    assert estimate_tokens(CORPUS[kind]) <= real_min * 1.6, (
        f"«{kind}»: оценка завышена больше чем в 1.6 раза — сожмём то, что влезало"
    )


def test_prose_is_not_treated_as_dense_markup():
    """Сплошная проза кодируется вдвое эффективнее разметки — формула обязана различать.

    Прежняя модель различала по АЛФАВИТУ, и это было ошибкой: замер показал, что
    предсказывает плотность разметки, а не кириллица.
    """
    prose = "Пользователь описывает ситуацию своими словами, довольно подробно. " * 4
    markup = "| a | b |\n|---|---|\n| 1 | 2 |\n" * 8

    assert len(prose) / estimate_tokens(prose) > len(markup) / estimate_tokens(markup)


def test_cyrillic_is_no_longer_twice_as_expensive():
    """Кириллица у нынешних токенизаторов дороже латиницы, но НЕ вдвое (замер: 4.15 против 5.53)."""
    ru = "Пользователь описывает ситуацию своими словами и уточняет детали. " * 4
    en = "The user describes the situation in their own words and adds detail. " * 4

    ru_density = len(ru) / estimate_tokens(ru)
    en_density = len(en) / estimate_tokens(en)

    assert 1.0 < en_density / ru_density < 1.4, "кириллица снова стоит как в старой формуле"
