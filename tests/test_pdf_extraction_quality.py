"""Плохое извлечение PDF отвергается, кириллица-mojibake чинится.

🔴 ЖИВОЙ ИНЦИДЕНТ. Пользователь приложил научную статью (PDF, две колонки, формулы,
графики) и попросил «улучшить текст». Агент ответил «вставьте текст, который нужно
улучшить» — он не увидел содержимого. Причина: opendataloader на сложной вёрстке вернул
1924 знака СИМВОЛЬНОЙ КАШИ (≥±−+ и подписи к осям), и это принималось как успех
(`if markdown: return markdown`), а связный PyPDF2-фолбэк на 49 117 знаков не пробовался.

Плюс PyPDF2 отдавал кириллицу как cp1251-байты в latin-1 обёртке («Âîçðàñò» вместо
«Возраст») — нечитаемо для модели.
"""

from __future__ import annotations

import pytest

from service.services.chat.application.use_cases.upload_file_use_case import (
    UploadFileUseCase,
    _fix_cp1251_mojibake,
    _text_quality,
)

# Символьная каша, какую отдал opendataloader на сложном PDF (доля «слов» ~0.2).
GARBAGE = "≥ + ± −\n\n≈\n\nP( | , )\n\nn 2\n\n= = >\n\nκ\n\n< ≥ ≈\n\n− → →\n" * 40
GOOD_RU = "Возраст-инвариантное сопоставление личности по естественно заякоренным постам. " * 20


class TestQualityMetric:
    def test_garbage_is_below_threshold(self):
        assert _text_quality(GARBAGE) < 0.35, "символьная каша прошла как читаемый текст"

    def test_coherent_text_is_above_threshold(self):
        assert _text_quality(GOOD_RU) >= 0.35, "связный текст ошибочно признан мусором"

    def test_short_text_is_not_judged(self):
        # Короткий легитимный документ без «слов» не должен браковаться.
        assert _text_quality("Итого: 42 ₽") == 1.0


class TestMojibakeRepair:
    def test_cp1251_cyrillic_is_restored(self):
        # Достаточно длинный mojibake (кандидатов > порога) чинится.
        garbled = "Âîçðàñò-èíâàðèàíòíîå ñîïîñòàâëåíèå ëè÷íîñòè ïî çàÿêîðåííûì ïîñòàì"
        out = _fix_cp1251_mojibake(garbled)
        assert out.startswith("Возраст-инвариантное сопоставление"), out

    def test_english_is_untouched(self):
        assert _fix_cp1251_mojibake("IEEE TRANSACTIONS") == "IEEE TRANSACTIONS"

    def test_western_european_diacritics_not_mangled(self):
        """⚠️ Редкие диакритики — НЕ mojibake: «café résumé» не должен стать кашей.

        Без порога кандидатов recode превратил бы é→й и сломал легитимный текст.
        """
        fr = "café résumé naïve Zürich" * 2  # единицы extended-символов, < порога
        assert _fix_cp1251_mojibake(fr) == fr, "западный текст с диакритиками испорчен recode'ом"

    def test_long_western_text_with_many_diacritics_survives(self):
        """⚠️ Даже при МНОГИХ диакритиках (кандидатов > порога) не ломаем латиницу.

        Отличие от mojibake — кандидаты recode'ятся в ОДИНОЧНЫЕ буквы среди латиницы, а
        не в кириллические слова. Guard по «кириллическим словам» это ловит; простой
        подсчёт кириллицы — нет (é→й создаёт кириллицу, но не слово).
        """
        fr = "Élève à l'école: café, résumé, naïveté, Zürich, œuvre, façade. " * 5
        assert _fix_cp1251_mojibake(fr) == fr, "длинный западный текст превращён в кашу"

    def test_valid_unicode_is_left_alone(self):
        # Уже нормальная кириллица + формула не должны «чиниться» повторно.
        good = "Возраст ≥ 18, точность ≈ 0.95"
        assert _fix_cp1251_mojibake(good) == good

    def test_math_symbols_survive_mixed_text(self):
        # Смешанный mojibake + юникод-математика: кириллица чинится, «≥» цел.
        # Повторяем, чтобы кандидатов хватило выше порога.
        out = _fix_cp1251_mojibake("Òî÷íîñòü ìîäåëè ïðèáëèæàåòñÿ ê ≥ 0.9 íà òåñòå")
        assert "Точность" in out and "≥" in out

    def test_pypdf_text_applies_mojibake_fix(self):
        """⚠️ Починка ПОДКЛЮЧЕНА к _pypdf_text, а не просто существует функцией."""
        import inspect

        src = inspect.getsource(UploadFileUseCase._pypdf_text)
        assert "_fix_cp1251_mojibake" in src, (
            "_pypdf_text не применяет починку кодировки — кириллица останется mojibake"
        )


@pytest.mark.asyncio
async def test_garbled_pdf_falls_back_to_pypdf(monkeypatch):
    """⚠️ ГЛАВНОЕ. opendataloader вернул мусор → берётся читаемый PyPDF2, не каша."""

    class _GarbageParser:
        def supports(self, name):
            return name.endswith(".pdf")

        async def parse(self, content, filename):
            return GARBAGE  # «успешный», но нечитаемый результат

    uc = UploadFileUseCase(
        file_service=None, media_analysis_port=None, document_parsing_port=_GarbageParser()
    )
    # PyPDF2 подменяем связным текстом — как если бы он извлёкся с реального PDF.
    monkeypatch.setattr(UploadFileUseCase, "_pypdf_text", staticmethod(lambda b: GOOD_RU))

    text, ftype = await uc._extract_text("статья.pdf", "application/pdf", b"%PDF-fake")

    assert text == GOOD_RU, "принят мусор opendataloader вместо читаемого PyPDF2"
    assert ftype == "pdf"


@pytest.mark.asyncio
async def test_good_opendataloader_result_is_kept(monkeypatch):
    """Читаемый markdown opendataloader берётся как есть — PyPDF2 не нужен."""

    class _GoodParser:
        def supports(self, name):
            return name.endswith(".pdf")

        async def parse(self, content, filename):
            return GOOD_RU

    called = {"pypdf": False}

    def _spy(b):
        called["pypdf"] = True
        return "не должно вызываться"

    uc = UploadFileUseCase(
        file_service=None, media_analysis_port=None, document_parsing_port=_GoodParser()
    )
    monkeypatch.setattr(UploadFileUseCase, "_pypdf_text", staticmethod(_spy))

    text, _ = await uc._extract_text("статья.pdf", "application/pdf", b"%PDF")

    assert text == GOOD_RU
    assert called["pypdf"] is False, "PyPDF2 звался зря — качественный markdown уже был"
