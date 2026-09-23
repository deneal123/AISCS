"""Контракт решения оркестратора и его починка при кривом ответе модели.

Оркестратор управляет ЧЕТЫРЬМЯ рычагами сразу (маршрут, поиск, план, декомпозиция), тогда
как прежний роутер портил при ошибке только маршрут. Поэтому чинить кривой ответ надо
пофильно: непонятное поле не должно отменять разобранные.
"""

from __future__ import annotations

from service.domain.routing.auto_decision import (
    SOURCE_LLM,
    AutoDecision,
    normalize_decision,
)


def test_full_answer_is_parsed():
    decision = normalize_decision(
        {
            "route": "web_search",
            "confidence": "high",
            "needs_fresh_data": True,
            "needs_plan": True,
            "multi_step": False,
            "reason": "не должен попасть в контракт",
        }
    )

    assert decision == AutoDecision(
        route="web_search",
        confidence="high",
        needs_fresh_data=True,
        needs_plan=True,
        multi_step=False,
        source=SOURCE_LLM,
    )


def test_unknown_route_keeps_the_strategies():
    """🔴 ПОФИЛЬНАЯ деградация: непонятный маршрут не отменяет разобранный план.

    «Не поняли одно поле — выбрасываем весь ответ» стоило бы лишнего вызова модели там,
    где ответ годен на восемь десятых.
    """
    decision = normalize_decision({"route": "телепатия", "needs_plan": True})

    assert decision is not None
    assert decision.route is None, "маршрут не отдан старому роутеру"
    assert decision.needs_plan is True, "разобранная стратегия потеряна из-за чужого поля"


def test_audio_route_from_the_model_is_dropped():
    """`audio_transcribe` выбирается по ТИПУ ВЛОЖЕНИЯ, а не по тексту.

    Маршрут распознавания речи, выбранный по словам, уводит запрос к файлу, которого
    пользователь не прикладывал. Та же защита в глубину уже стоит в оркестраторе и в
    роутере модели — здесь третий рубеж.
    """
    assert normalize_decision({"route": "audio_transcribe"}).route is None


def test_garbage_is_not_a_decision():
    """Не dict — значит разбирать нечего: `None` включает прежнее поведение целиком."""
    assert normalize_decision(None) is None
    assert normalize_decision("general") is None
    assert normalize_decision(["general"]) is None


def test_non_boolean_flags_do_not_spend_money():
    """🔴 Всё непонятное → False. `True` здесь означает списанные кредиты.

    Модель, не сумевшая вернуть булево, не заслуживает доверия и в самом решении.
    """
    decision = normalize_decision(
        {"route": "general", "needs_fresh_data": "yes", "multi_step": 1, "needs_plan": "true"}
    )

    assert (decision.needs_fresh_data, decision.multi_step, decision.needs_plan) == (
        False,
        False,
        False,
    )


def test_bad_confidence_falls_back_to_low():
    """Мусор → low: высокая уверенность короткозамыкает ответ, низкая — нет."""
    assert normalize_decision({"route": "general", "confidence": "очень"}).confidence == "low"
    assert normalize_decision({"route": "general", "confidence": 0.9}).confidence == "low"


def test_model_reason_is_ignored_and_policy_code_is_bounded():
    """Свободный текст модели не должен стать trace/persistence metadata."""
    decision = normalize_decision({"route": "general", "reason": "секретный marker"})

    assert decision.reason_code == "model_classification"
    assert not hasattr(decision, "reason")
