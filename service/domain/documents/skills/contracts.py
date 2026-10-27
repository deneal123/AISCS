"""Versioned editorial skills layered over deterministic document profiles."""

from __future__ import annotations

from dataclasses import dataclass

from service.domain.documents.skills.profiles import DOCUMENT_PROFILE_IDS


@dataclass(frozen=True, slots=True)
class DocumentSkill:
    skill_id: str
    profile_id: str
    instruction: str
    checklist: tuple[str, ...]

    def system_instruction(self) -> str:
        checks = "\n".join(f"- {item}" for item in self.checklist)
        return f"{self.instruction}\n\nОбязательная самопроверка:\n{checks}"


_COMMON = (
    (
        "Верни только семантический DocumentDraft через обязательный вызов функции: "
        "заголовок и типизированные блоки со стабильными block_id."
    ),
    (
        "Не создавай LaTeX, преамбулу, настройки пакетов, класс документа, пути файлов или "
        "BibTeX: их детерминированно формирует доверенный обработчик профиля."
    ),
    "Не используй абсолютные пути, сетевые ресурсы и команды операционной системы.",
    "Таблицы оформляй через booktabs/tabularx/longtable и не допускай выхода за поля.",
    "Не выдумывай факты, источники, реквизиты, даты, суммы или персональные данные.",
)

_SKILLS = {
    "generic_article": DocumentSkill(
        "scientific_article.v1",
        "generic_article",
        (
            "Создай строгую научную статью: название, аннотация, введение, метод, "
            "результаты, заключение и литература. Каждое фактическое утверждение, "
            "требующее источника, связывай с зарегистрированным идентификатором источника."
        ),
        (
            *_COMMON,
            "Каждая библиографическая запись должна соответствовать реально данному источнику.",
        ),
    ),
    "ieee_journal": DocumentSkill(
        "ieee_article.v1",
        "ieee_journal",
        (
            "Создай журнальную статью IEEE с автором, аннотацией, ключевыми словами и компактной "
            "двухколоночной структурой; оформление издателя задаётся профилем."
        ),
        (*_COMMON, "Не изменяй геометрию, колонки и класс документа издателя."),
    ),
    "aaai_conference": DocumentSkill(
        "aaai_article.v1",
        "aaai_conference",
        (
            "Создай анонимизированную конференционную статью с "
            "author=Anonymous Submission, аннотацией, разделами и литературой."
        ),
        (*_COMMON, "В режиме подачи не раскрывай автора, организацию и метаданные PDF."),
    ),
    "beamer_16_9": DocumentSkill(
        "beamer_presentation.v1",
        "beamer_16_9",
        (
            "Создай горизонтальную PDF-презентацию. Один блок слайда — одна мысль; "
            "короткие заголовки, крупный текст, осмысленные таблицы и схемы."
        ),
        (*_COMMON, "Не помещай длинные абзацы и более семи пунктов на один слайд."),
    ),
    "legal_ru": DocumentSkill(
        "russian_legal.v1",
        "legal_ru",
        (
            "Создай российский A4 юридический документ с нумерованными разделами, "
            "реквизитами и блоками подписей. Все неизвестные критичные значения "
            "оставляй как {{UPPER_SNAKE_CASE}}."
        ),
        (*_COMMON, "Не заменяй заполнители предположениями; они блокируют финальную публикацию."),
    ),
    "generic_report": DocumentSkill(
        "technical_report.v1",
        "generic_report",
        (
            "Создай структурированный A4 отчёт или техническое задание: цель, "
            "область, требования, архитектура, риски, проверки и приложения."
        ),
        _COMMON,
    ),
    "generic_document": DocumentSkill(
        "generic_document.v1",
        "generic_document",
        (
            "Создай аккуратный произвольный A4 PDF-документ с ясной иерархией "
            "заголовков и переиспользуемыми LaTeX-компонентами."
        ),
        _COMMON,
    ),
}

if set(_SKILLS) != set(DOCUMENT_PROFILE_IDS):
    raise RuntimeError("document_profile_contract")


def skill_for_profile(profile_id: str) -> DocumentSkill:
    return _SKILLS.get(profile_id, _SKILLS["generic_document"])
