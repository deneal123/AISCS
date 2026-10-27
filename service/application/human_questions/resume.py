"""Admit a private answered checkpoint; public message/session data cannot resume it."""

import json

from service.domain.execution.context import RunExecutionContext
from service.shared.human_question import HumanQuestionError, parse_resumed_question_continuation

RESUME_KEY = "_human_question_resume_v1"


def admit_question_resume(execution: RunExecutionContext, selected_model: str | None) -> bool:
    ref = execution.resources.workspace_ref or {}
    if RESUME_KEY not in ref:
        return False
    if not execution.policy.flag("human_questions_enabled"):
        raise HumanQuestionError("human_question_unavailable")
    resumed = parse_resumed_question_continuation(ref[RESUME_KEY])
    if resumed["model"] != selected_model:
        raise HumanQuestionError("human_question_unavailable")
    execution.question.resume_json = json.dumps(resumed, ensure_ascii=False)
    return True
