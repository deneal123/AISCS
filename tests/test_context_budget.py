"""Тесты Фазы 3: токенный бюджет, категоризация ошибок, суммаризация, контекст."""

import httpx
import pytest

from service.domain.pipeline import (
    context_assembler,
    context_budget,
    errors,
)
from service.shared import token_budget


# --------------------------------------------------------------------------- #
# token_budget                                                                  #
# --------------------------------------------------------------------------- #
def test_estimate_tokens():
    assert token_budget.estimate_tokens("") == 0
    assert token_budget.estimate_tokens("a" * 8) == 2  # латиница ≈4 симв/ток → ceil(8/4)
    assert token_budget.estimate_tokens("x") == 1


def test_estimate_tokens_cyrillic_costs_a_bit_more_than_latin():
    """Кириллица дороже латиницы, но НЕ вдвое — коэффициенты откалиброваны замером.

    ⚠️ Тест переписан осознанно. Он закреплял «сплошная кириллица ≈2.5 симв/ток», и это
    было верно для прежних токенизаторов. Сверка с настоящими (RouterAI/gpt-4o-mini и
    GigaChat-2-Max) дала 4.15-4.46 симв/ток на русской прозе: старая формула завышала её
    на 51% и при этом ЗАНИЖАЛА markdown на 9%. Абсолютные числа держит
    `test_token_estimate_calibration.py` против замера, здесь — только соотношение.
    """
    ru = "б" * 40
    en = "a" * 40

    assert token_budget.estimate_tokens(ru) > token_budget.estimate_tokens(en)
    assert token_budget.estimate_tokens(ru) / token_budget.estimate_tokens(en) < 1.4, (
        "вернулась старая двукратная наценка на кириллицу"
    )


def test_allocate_budget_proportional():
    out = token_budget.allocate_budget(100, {"a": 1, "b": 1, "c": 2})
    assert out == {"a": 25, "b": 25, "c": 50}
    assert token_budget.allocate_budget(0, {"a": 1}) == {"a": 0}
    assert token_budget.allocate_budget(100, {"a": 0}) == {"a": 0}


def test_trim_messages_keeps_newest():
    msgs = [{"role": "user", "content": "a" * 35} for _ in range(4)]  # ~10 ток. каждое
    kept = token_budget.trim_messages_to_tokens(msgs, 25)  # влезает 2 свежих
    assert len(kept) == 2
    assert token_budget.trim_messages_to_tokens(msgs, 0) == []
    # бюджет меньше одного сообщения — оставляем хотя бы одно (свежее)
    assert len(token_budget.trim_messages_to_tokens(msgs, 1)) == 1


def test_trim_messages_truncates_oversized_newest():
    # P1.2: одно огромное свежее сообщение (вставленная простыня) раньше впускалось
    # ЦЕЛИКОМ (kept_reversed пуст → лимит не срабатывал) и переполняло окно. Теперь
    # оно обрезается по бюджету, а не проходит как есть.
    huge = {"role": "user", "content": "a" * 4000}  # ~1000 токенов
    kept = token_budget.trim_messages_to_tokens([huge], 20)
    assert len(kept) == 1
    assert token_budget.estimate_tokens(kept[0]["content"]) <= 20
    assert len(kept[0]["content"]) < 4000  # реально обрезано, а не впущено целиком


# --------------------------------------------------------------------------- #
# errors.categorize                                                             #
# --------------------------------------------------------------------------- #
class _Status(Exception):
    def __init__(self, code):
        self.status_code = code


def test_categorize_maps_categories():
    assert errors.categorize(TimeoutError()).category == "timeout"
    assert errors.categorize(httpx.ConnectError("x")).category == "network"
    assert errors.categorize(_Status(429)).category == "rate_limit"
    assert errors.categorize(_Status(401)).category == "auth"
    assert errors.categorize(_Status(400)).category == "config"
    assert errors.categorize(RuntimeError("boom")).category == "unknown"
    assert errors.categorize(httpx.ConnectError("x")).user_message  # не пустое


# --------------------------------------------------------------------------- #
# P1.2: промпт не должен вылезать за окно на большом вводе + истории            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_context_never_overflows_window_with_large_input_and_history(monkeypatch):
    """Регрессия P1.2: длинный вопрос ужимал `available` к нулю, но история
    продолжала требовать всю свою долю (не клампилась), а safety-net её не трогал →
    итог вылезал за usable, провайдер отвергал промпт. Теперь и история клампится
    в остаток, и safety-net её дожимает."""
    from service.settings import config

    async def _tiny_window(model_id, cfg):
        return 400, True  # крошечное окно → жёсткая конкуренция ввод/история

    monkeypatch.setattr(context_budget, "resolve_window", _tiny_window)

    # Большой ввод почти съедает окно (available→мало), а история — много МЕЛКИХ
    # сообщений: без клампа они наберут всю свою (неурезанную) долю и переполнят окно.
    long_input = "тест вопрос " * 22  # ~100+ токенов при usable≈128
    history = [{"role": "user", "content": "реплика " * 6} for _ in range(6)]

    assembled = await context_assembler.assemble_context(
        model_id="tiny",
        config=config,
        user_input=long_input,
        history=history,
    )

    # Инвариант: итоговый промпт укладывается в usable — провайдер его не отвергнет.
    assert assembled.budget.usable > 0
    assert assembled.used <= assembled.budget.usable


# --------------------------------------------------------------------------- #
# Обрезка использует бюджет, но НЕ переполняет его                             #
# --------------------------------------------------------------------------- #
# ⚠️ Текст отдаётся ФАБРИКОЙ, а не значением: pytest вшивает параметр в имя теста, и
# восьмитысячесимвольная строка превращала идентификатор в мусор на сотню килобайт.
_TRIM_CASES = {
    "латиница": lambda: "a" * 8000,
    "кириллица": lambda: "я" * 8000,
    "смешанный": lambda: "header line " + "я" * 4000 + "tail" * 1000,
    "код": lambda: "def f():\n    return 1\n" * 400,
    "json": lambda: '{"k":"v","n":123},' * 500,
}


@pytest.mark.parametrize("name", sorted(_TRIM_CASES))
def test_trim_never_overflows_the_budget(name):
    """⚠️ ПЕРЕБОР ОПАСНЕЕ НЕДОБОРА: это переполнение окна модели и 400 от провайдера.

    Проверяется ИТОГОВАЯ строка, а не срез: пометка «обрезано по бюджету» — это тоже
    токены, причём кириллические, то есть дорогие. Первая версия правки давала 1002
    токена при бюджете 1000 ровно из-за неё, а на смешанном тексте — 1254, потому что
    плотность средняя по всему тексту, а оставляем мы начало.
    """
    out = token_budget.trim_text_to_tokens(_TRIM_CASES[name](), 1000)

    assert token_budget.estimate_tokens(out) <= 1000, f"{name}: обрезка переполнила бюджет"


def test_trim_uses_the_budget_it_was_given():
    """⚠️ РЕГРЕССИЯ: латиница резалась на 37% глубже, чем нужно.

    `estimate_tokens` адаптивен (2.5 симв/ток для кириллицы, 4.0 для латиницы), а обрезка
    считала по фиксированным 2.5. Просим уложить в 1000 токенов — получаем 627, то есть
    больше трети выделенного окна не используется. Бьёт по коду, логам и JSON, то есть
    ровно по тому, что чаще всего прикладывают файлом.
    """
    latin = "a" * 8000

    used = token_budget.estimate_tokens(token_budget.trim_text_to_tokens(latin, 1000))

    assert used >= 850, f"использовано лишь {used} из 1000 токенов бюджета"


def test_trim_returns_text_untouched_when_it_fits():
    """Влезает — не трогаем: ни обрезки, ни пометки."""
    text = "короткий текст"

    assert token_budget.trim_text_to_tokens(text, 1000) == text


def test_chars_for_tokens_stays_conservative():
    """⚠️ У `chars_for_tokens` пессимизм УМЕСТЕН и остаётся.

    Она отвечает на вопрос «сколько влезет НАВЕРНЯКА» и текста не видит: ошибка в
    бо́льшую сторону означала бы переполнение. Адаптивность нужна там, где текст есть, —
    в `trim_text_to_tokens`.
    """
    assert token_budget.chars_for_tokens(1000) == 2500
