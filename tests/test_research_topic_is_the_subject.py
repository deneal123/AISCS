"""В ресёрч уезжает ПРЕДМЕТ запроса, а не поручение ассистенту.

🔴 Живой случай: «проведи глубокий поиск на тему страдания по каждой бывшей с одинаковой
силой» ушло в ресёрчер ЦЕЛИКОМ. Он получил «проведи глубокий поиск на тему…» как предмет
изучения, раскрутил его до общего «страдание» и вернул обзор Достоевского, буддизма и
православного богословия — 88 тысяч токенов и 2 минуты на то, о чём не спрашивали.

Команда адресована НАМ и в предмет исследования не входит.
"""

from __future__ import annotations

from service.domain.subagents import context_query


def test_condense_prompt_strips_the_command():
    """Правило объявлено в системном промпте переформулировки."""
    prompt = context_query._CONDENSE_SYSTEM

    assert "команду" in prompt, "команда не отделена от предмета — уедет в тему целиком"
    assert "ПРЕДМЕТ" in prompt
    assert "Сохраняй все уточнения предмета" in prompt, (
        "без этого команда уйдёт вместе с уточнениями и тема схлопнется до общей"
    )


def test_research_and_search_share_one_condense_point():
    """🔴 Точка ОДНА на все внешние инструменты.

    Иначе правило «убирай команду» пришлось бы дублировать в каждом субагенте, и они
    разошлись бы молча: у поиска тема была бы чистой, у ресёрча — с поручением.
    """
    import inspect

    from service.domain.subagents import deep_research, image_generation

    for module in (deep_research, image_generation):
        assert "build_standalone_query" in inspect.getsource(module), (
            f"{module.__name__} строит тему сам — правило до него не доедет"
        )


def test_psychologist_asks_about_the_mechanism_not_the_concept():
    """Личный вопрос — про механизм переживания, а не про философию понятия."""
    from service.domain.persona import registry, slots

    lens = registry.build_lens(["psychologist"])
    fragment = lens.slot(slots.SEARCH_QUERY)

    assert fragment, "психолог не влияет на формулировку запроса — вопрос уйдёт общей темой"
    assert "МЕХАНИЗМ" in fragment
    assert "философ" in fragment.lower(), "не сказано, чего избегать — а мимо ушло именно туда"


def test_research_aux_uses_the_selected_model():
    """🔴 Тот же aux русифицирует отчёт — то есть пишет текст, который человек читает."""
    import inspect

    from service.domain.subagents import deep_research

    src = inspect.getsource(deep_research)
    assert "pick_meta_model(models, self.preferred_model())" in src, (
        "ресёрч снова берёт произвольную модель вместо выбранной"
    )
