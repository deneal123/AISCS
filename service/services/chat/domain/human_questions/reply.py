"""Unprivileged reply selection; never a workspace capability or provider transcript."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from service.services.chat.domain.documents.context import DocumentContext


class IdeQuestionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: UUID
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    choice_id: str | None = Field(default=None, max_length=32)
    text: str | None = Field(default=None, max_length=4000)


class QuestionReplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent_id: UUID
    answer: AnswerInput
    surface: Literal["ide", "pdf"]
    ide_context: IdeQuestionContext | None = None
    document_context: DocumentContext | None = None

    @model_validator(mode="after")
    def selected_project(self):
        if (
            not self.intent_id.int
            or (self.surface == "ide") != (self.ide_context is not None)
            or (self.surface == "pdf") != (self.document_context is not None)
        ):
            raise ValueError("human_question_invalid")
        return self
