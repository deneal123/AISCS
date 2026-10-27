"""Specialization must not convert assistant role assignments into user identity."""

from service.domain.persona.registry import build_lens
from service.domain.subagents.general import GENERAL_PROMPT, PERSONA_OVERRIDES


def test_conversational_boundary_precedes_task_policy_and_survives_persona():
    assert GENERAL_PROMPT.index("Обычная беседа и роли") < GENERAL_PROMPT.index("Режим работы")
    prompt = GENERAL_PROMPT
    for original, replacement in PERSONA_OVERRIDES:
        prompt = prompt.replace(original, replacement)
    assert "не имя пользователя" in prompt
    assert "без просьбы" in prompt
    assert "Явная поправка пользователя важнее" in prompt
    assert "Не выдавай их за" in prompt


def test_psychologist_method_is_request_scoped():
    section = build_lens(["psychologist"]).section()
    assert "При запросе психологического разбора" in section
    assert "В обычной беседе отвечай естественно" in section
    assert "Не ставь диагнозов" in section
