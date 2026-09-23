"""Сжатие файла текущей задачи держит СЫРОЕ содержимое (регресс: «не вижу файл»).

Юзер приложил CSV для анализа. Map-reduce пересказ выходил СИЛЬНО меньше бюджета
(модель ужимает агрессивно) → в контекст попадал прозаический пересказ вместо данных,
и модель отвечала «не вижу прикреплённый файл». Теперь простаивающий бюджет добивается
сырой головой файла: модель видит реальные строки и узнаёт файл.
"""

import pytest

from service.domain.pipeline import context_compressor as cc


async def _fixed_model() -> str:
    """Модель для сжатия резолвится ОДИН раз до map-фазы — подменяем её целиком.

    Иначе тест полез бы в сеть за каталогом моделей.
    """
    return "test-model"


@pytest.mark.asyncio
async def test_files_compression_fills_budget_with_raw_head(monkeypatch):
    # LLM-сжатие возвращает КОРОТКИЙ пересказ (реальная модель ужимает намного ниже cap).
    async def _fake_summarize(text, target_tokens, kind, usage_out=None, model=""):
        return "Файл содержит табличные данные с колонками."

    monkeypatch.setattr(cc, "_summarize", _fake_summarize)
    monkeypatch.setattr(cc, "_pick_model", _fixed_model)

    # Табличные данные, крупнее бюджета, но бюджет большой → есть headroom под сырьё.
    raw = "\n\n".join(f"row{i},value{i},2023-10-{(i % 28) + 1:02d}" for i in range(1, 400))
    out = await cc.compress_to_budget(raw, target=900, kind="files")

    # Простаивающий бюджет заполнен СЫРОЙ головой — реальные строки на месте.
    assert "Содержимое приложенного файла" in out
    assert "row1," in out and "value1" in out, "реальные данные файла потеряны"
    # Пересказ целого тоже присутствует.
    assert "Сжатый пересказ файла" in out


@pytest.mark.asyncio
async def test_non_files_kind_stays_pure_summary(monkeypatch):
    """Память/знания сырьём не добиваем — там нужен именно пересказ, не выдержки."""

    async def _fake_summarize(text, target_tokens, kind, usage_out=None, model=""):
        return "Пересказ памяти."

    monkeypatch.setattr(cc, "_summarize", _fake_summarize)
    monkeypatch.setattr(cc, "_pick_model", _fixed_model)
    raw = "\n\n".join(f"Факт о пользователе номер {i}." for i in range(1, 400))
    out = await cc.compress_to_budget(raw, target=900, kind="memory")
    assert "Содержимое приложенного файла" not in out
    assert out == "Пересказ памяти."


@pytest.mark.asyncio
async def test_small_file_returned_raw_without_llm(monkeypatch):
    """Влезает в бюджет → LLM не зовём, отдаём как есть (сырьё целиком)."""
    called = {"n": 0}

    async def _fake_summarize(text, target_tokens, kind, usage_out=None, model=""):
        called["n"] += 1
        return "нельзя-звать"

    monkeypatch.setattr(cc, "_summarize", _fake_summarize)
    monkeypatch.setattr(cc, "_pick_model", _fixed_model)
    raw = "city,sales\nMoscow,100\nKazan,80\n"
    out = await cc.compress_to_budget(raw, target=5000, kind="files")
    assert out == raw.strip()  # влезло — отдаём сырьё как есть (strip хвостовых \n)
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_compressed_section_reports_its_real_size():
    """⚠️ Сжатая секция обязана сообщать СВОЙ реальный размер в токенах.

    Мутация показала дыру: обнуление `section.tokens` после сжатия не ловил ни один тест.
    А число это не декоративное — из него складывается `assembled.used`, по нему кольцо
    на фронте показывает занятость окна, и по нему же страховочная сетка решает, что
    резать. Секция, объявившая себя нулевой, невидима для сетки и врёт пользователю.
    """
    from service.domain.pipeline.context_assembler import ContextSection, _fit
    from service.shared.token_budget import estimate_tokens

    raw = "очень длинный исходный текст " * 200
    # `title` и `compressible` — вычисляемые свойства секции, а не поля: вид секции
    # (`files`) сам определяет и заголовок, и то, что её можно сжимать.
    section = ContextSection(kind="files", raw=raw, raw_tokens=estimate_tokens(raw), budget=300)

    async def _compressor(_raw, _target, _kind):
        return "короткий пересказ файла"

    await _fit(section, _compressor)

    assert section.compressed is True
    assert section.tokens == estimate_tokens(section.content) > 0
