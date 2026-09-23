"""Частичный сбой виден в РЕЗУЛЬТАТЕ, а не только в трейсе.

⚠️ Самая коварная из деградаций этого сервиса: наружу она выглядит как полный успех.

В мульти-интенте упавший шаг подставляет в синтез строку «[Шаг не выполнен: …]»
(`execution_plan`), синтез добросовестно строит по ней связный текст — значит ответ
непустой. А `error_messages` использовались ТОЛЬКО при пустом ответе, поэтому в
результат, который backend персистит и показывает, не попадало ничего: ни признака, ни
текста ошибки.

ERROR-событие при этом уходит в трейс — но трейс живёт отдельно от сохранённого итога.
Пользователь получает ответ, собранный без половины работы, и отличить его от честного
нечем. Аналитика видит успешный прогон.

## Чего тест НЕ требует

Он не требует подменять ответ на «провайдер недоступен»: текст осмысленный, и заменять
его было бы хуже для пользователя. Требуется ровно пометка.
"""

from __future__ import annotations

from service.application.reply_assembler import ReplyAssembler
from service.application.use_cases.agent_execution_use_cases import (
    PostprocessAgentReplyUseCase,
)


def _assembler(*, reply_parts: list[str], errors: list[str]) -> ReplyAssembler:
    asm = ReplyAssembler()
    asm.reply_parts.extend(reply_parts)
    asm.error_messages.extend(errors)
    return asm


def test_failed_step_is_marked_even_when_the_answer_arrived():
    """⚠️ ГЛАВНОЕ: ответ есть, шаг упал — результат обязан это признать."""
    asm = _assembler(
        reply_parts=["Вот сводка по вашему запросу."],
        errors=["web_search: провайдер вернул 503"],
    )

    reply, metadata = PostprocessAgentReplyUseCase().execute(reply_assembler=asm, metadata={})

    assert reply == "Вот сводка по вашему запросу.", "ответ подменять не требуется"
    assert metadata.get("partial_failure") is True, (
        "прогон с упавшим шагом сохранён как полностью успешный — отличить его от "
        "честного ответа нечем ни пользователю, ни аналитике"
    )
    assert metadata.get("step_errors") == ["internal"]
    assert "web_search" not in str(metadata)
    assert metadata["execution_status"] == "partial"


def test_clean_run_is_not_marked():
    """⚠️ Штатный прогон не помечается: иначе метка перестанет что-либо значить."""
    asm = _assembler(reply_parts=["Обычный ответ."], errors=[])

    _, metadata = PostprocessAgentReplyUseCase().execute(reply_assembler=asm, metadata={})

    assert "partial_failure" not in metadata
    assert "step_errors" not in metadata
    assert metadata["execution_status"] == "completed"


def test_deadline_takes_precedence_over_other_partial_markers():
    asm = _assembler(reply_parts=["Часть ответа."], errors=["поздний шаг не завершился"])

    _, metadata = PostprocessAgentReplyUseCase().execute(
        reply_assembler=asm, metadata={"deadline_exceeded": True}
    )

    assert metadata["execution_status"] == "timed_out"


def test_empty_reply_still_reports_provider_unavailable():
    """Прежнее поведение сохранено: пустой ответ по-прежнему честная недоступность."""
    asm = _assembler(reply_parts=[], errors=["провайдер лёг"])

    reply, metadata = PostprocessAgentReplyUseCase().execute(reply_assembler=asm, metadata={})

    assert metadata.get("provider_unavailable") is True
    assert metadata["execution_status"] == "failed"
    assert reply.strip(), "пустой ответ должен быть заменён объяснением"


def test_error_list_is_bounded():
    """⚠️ Потолок обязателен: metadata уезжает в backend целиком.

    Мульти-интент с большим числом шагов иначе раздул бы результат неограниченно —
    ровно та беда, что уже была с артефактами под-шагов.
    """
    asm = _assembler(
        reply_parts=["ответ"],
        errors=[f"шаг {i}: очень длинное описание ошибки " + "x" * 2000 for i in range(20)],
    )

    _, metadata = PostprocessAgentReplyUseCase().execute(reply_assembler=asm, metadata={})

    errors = metadata["step_errors"]
    assert len(errors) <= 5, f"в результат уехало {len(errors)} ошибок без потолка"
    assert errors == ["internal"]
    assert "очень длинное описание" not in str(metadata)
