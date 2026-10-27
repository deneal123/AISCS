"""Private queue claim: IDs only, never prompt, answer, transcript or capability."""

from dataclasses import dataclass
from uuid import UUID, uuid5


@dataclass(frozen=True, slots=True)
class QuestionDispatch:
    job_id: UUID
    user_id: UUID
    thread_id: UUID
    question_id: UUID
    claim_id: UUID

    def __post_init__(self):
        if any(
            not isinstance(value, UUID) or not value.int
            for value in (
                self.job_id,
                self.user_id,
                self.thread_id,
                self.question_id,
                self.claim_id,
            )
        ) or self.job_id != uuid5(self.question_id, "gpthub:human-question:resume:v1"):
            raise ValueError("human_question_dispatch_invalid")

    @property
    def task_id(self) -> str:
        return str(self.job_id)
