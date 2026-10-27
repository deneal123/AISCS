"""Bounded private document target. It is never itself message metadata."""

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    expected_revision: str = Field(min_length=1, max_length=64)
    authoring_version: int = Field(default=0, ge=0, le=1_000_000)
    draft_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    block_ids: list[str] = Field(default_factory=list, max_length=120)

    @field_validator("path")
    @classmethod
    def relative_project(cls, value: str) -> str:
        if (
            value.startswith("/")
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("invalid document target")
        return value

    @field_validator("block_ids")
    @classmethod
    def block_identifiers(cls, value: list[str]) -> list[str]:
        import re

        if len(value) != len(set(value)) or any(
            re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", item) is None for item in value
        ):
            raise ValueError("invalid document blocks")
        return value


def document_project_id(user_id: str, thread_id: str, path: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"gpthub-document:{user_id}:{thread_id}:{path}"))
