"""В долговременную память попадает сказанное ПОЛЬЗОВАТЕЛЕМ, а не домыслы ассистента.

🔴 НАЙДЕНО ЗАМЕРОМ ПО ЖИВОЙ БАЗЕ. В `profile.user_memory_facts` на dev лежало, например,
`identity/роль = «терпеливый преподаватель»` и `context/уровень = «новичок / средний /
продвинутый»`. Первое ассистент сказал О СЕБЕ, второе — перечень вариантов из его ВОПРОСА.
Ни то, ни другое пользователь не говорил.

Прогон экстрактора это подтвердил дословно. На диалоге

    Пользователь: посчитай 2+2
    Ассистент: 4. Вы, похоже, начинающий программист и любите Python.

в память уходили ДВА факта: «профессия: начинающий программист» и «любимая технология:
Python». Цена ошибки не в мусоре: эти факты потом едут в промпт КАЖДОГО следующего хода и
меняют ответы — платформа «помнит» о человеке то, чего он не говорил.

Правка двойная, и одной половины было мало (замерено):
* правило в системном промпте — сократило два ложных факта до одного;
* МЕТКА В КАЖДОЙ РЕПЛИКЕ ассистента — убрала последний.

⚠️ Поведение LLM тестом не закрепить, поэтому здесь стерегутся СТРУКТУРНЫЕ условия, при
которых замер получился: метка на месте, правило в промпте, реплики ассистента не выброшены.
"""

from __future__ import annotations

from service.services.analytics.application.memory_service import (
    _FACT_EXTRACTION_SYSTEM,
    MemoryService,
)

DIALOG = [
    {"role": "user", "content": "посчитай 2+2"},
    {"role": "assistant", "content": "4. Вы, похоже, начинающий программист."},
    {"role": "user", "content": "да, новичок"},
]


def _flat(text: str) -> str:
    """Смятые переносы: промпт свёрстан по ширине, правило не должно зависеть от разрыва."""
    return " ".join(str(text).lower().split())


# --- метка в транскрипте ----------------------------------------------------------------- #


def test_assistant_lines_are_marked_as_no_evidence():
    """🔴 ГЛАВНОЕ. Метка стоит вплотную к тексту — правило в шапке промпта модель пропускала."""
    transcript = MemoryService._format_transcript(DIALOG)

    assert "Ассистент (НЕ ИСТОЧНИК ФАКТОВ):" in transcript, (
        "реплики ассистента снова подаются как обычное свидетельство — домыслы уйдут в память"
    )


def test_every_assistant_line_carries_the_mark():
    """⚠️ Метка на КАЖДОЙ строке, а не только на первой: пометив одну, мы разрешили бы
    остальные, а домысел приходит в любой из них."""
    dialog = DIALOG + [{"role": "assistant", "content": "И вы любите Python."}]

    lines = [
        line
        for line in MemoryService._format_transcript(dialog).splitlines()
        if line.startswith("Ассистент")
    ]

    assert len(lines) == 2
    assert all("НЕ ИСТОЧНИК ФАКТОВ" in line for line in lines)


def test_user_lines_are_not_marked():
    """🔴 ГРАНИЦА. Пометить и пользователя значило бы отменить источник фактов целиком."""
    lines = [
        line
        for line in MemoryService._format_transcript(DIALOG).splitlines()
        if line.startswith("Пользователь")
    ]

    assert len(lines) == 2
    assert all("НЕ ИСТОЧНИК" not in line for line in lines)


def test_assistant_lines_are_kept_not_dropped():
    """🔴 ГРАНИЦА, БЕЗ КОТОРОЙ ПОЧИНКА ЛОМАЕТ ДРУГОЕ. Соблазн был выбросить реплики
    ассистента вовсе — тогда «да, новичок» не к чему отнести, и подтверждённый человеком
    факт потерялся бы. Замер это подтвердил: с репликами ассистента подтверждение
    извлекается, без них его смысл теряется."""
    transcript = MemoryService._format_transcript(DIALOG)

    assert "начинающий программист" in transcript, "реплики ассистента выброшены из контекста"
    assert "да, новичок" in transcript


def test_the_transcript_is_still_bounded():
    """⚠️ Потолок 6000 символов — за экстракцию платят токенами каждого хода."""
    long_dialog = [{"role": "user", "content": "я" * 5000} for _ in range(5)]

    assert len(MemoryService._format_transcript(long_dialog)) <= 6000


def test_empty_messages_are_skipped():
    """⚠️ Пустая реплика дала бы строку «Ассистент (НЕ ИСТОЧНИК ФАКТОВ):» без содержания."""
    transcript = MemoryService._format_transcript(
        [{"role": "user", "content": "   "}, {"role": "assistant", "content": ""}]
    )

    assert transcript == ""


# --- правило в промпте ------------------------------------------------------------------- #


def test_the_prompt_names_the_only_source_of_facts():
    """⚠️ Метка без правила — просто странная строка: модели надо сказать, что она значит."""
    flat = _flat(_FACT_EXTRACTION_SYSTEM)

    assert "только реплики" in flat, "источник фактов в промпте не назван единственным"
    assert "не является никогда" in flat, "слова ассистента нигде не объявлены несвидетельством"


def test_the_prompt_shows_the_measured_mistakes():
    """🔴 Примеры взяты ИЗ ЗАМЕРА, а не выдуманы: именно эти три формы и просачивались."""
    flat = _flat(_FACT_EXTRACTION_SYSTEM)

    for wrong in ("начинающий программист", "новичок / средний / продвинутый", "преподавателем"):
        assert wrong in flat, f"замеренная ошибка не названа в промпте: {wrong}"


def test_the_prompt_keeps_confirmation_as_a_valid_source():
    """🔴 ГРАНИЦА В ТЕКСТЕ. Без явного разрешения «ассистент спросил → человек подтвердил»
    экстрактор отбросил бы и подтверждённые факты — потерять их хуже, чем лишние."""
    flat = _flat(_FACT_EXTRACTION_SYSTEM)

    assert "подтвердил" in flat, "подтверждение пользователем не названо источником факта"
