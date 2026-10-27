"""Private state for a single parked question; no worker or provider waits here."""

import json
from dataclasses import dataclass, field

from service.shared.human_question import HumanQuestionError, QuestionPrompt


@dataclass(slots=True)
class HumanQuestionSession:
    prompt: QuestionPrompt | None = field(default=None, repr=False)
    continuation_json: str | None = field(default=None, repr=False)
    resume_json: str | None = field(default=None, repr=False)
    failed: bool = False

    def resumed_messages(self, model: str) -> list[dict] | None:
        if self.resume_json is None:
            return None
        checkpoint = json.loads(self.resume_json)
        if checkpoint["model"] != model:
            raise HumanQuestionError("human_question_unavailable")
        # Every call gets a fresh copy; the original checkpoint stays immutable.
        return checkpoint["messages"]

    @property
    def waiting(self) -> bool:
        return self.prompt is not None and self.continuation_json is not None and not self.failed


def question_instructions() -> str:
    from service.domain.execution.context import current_execution

    execution = current_execution()
    if execution is None or not execution.policy.flag("human_questions_enabled"):
        return ""
    return (
        "Если без существенного решения пользователя продолжить нельзя, вызови "
        "ask_user_question отдельно от других инструментов. В этом случае не вызывай "
        "финальный инструмент и не объявляй задачу завершённой. Ясные задания выполняй "
        "без лишних уточнений; сначала проверь доступные исходники."
    )
