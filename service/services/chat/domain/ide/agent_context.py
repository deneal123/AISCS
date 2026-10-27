"""Unprivileged IDE selection. No binding, capability, source bytes or run consent."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from service.services.chat.domain.ide.files import validate_path


class IdeAgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: UUID
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def selected_source(self):
        if self.path is not None:
            validate_path(self.path)
        elif self.digest is not None:
            raise ValueError("digest_requires_path")
        return self
