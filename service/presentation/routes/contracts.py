"""Private request contracts shared by workspace route groups."""

from __future__ import annotations

from domain.contracts import DEFAULT_TTL_SEC
from pydantic import BaseModel, Field


class CreateRequest(BaseModel):
    user_id: str
    ttl_sec: float = DEFAULT_TTL_SEC
    policy: dict | None = None


class ExecRequest(BaseModel):
    user_id: str
    token: str
    command: str = Field(min_length=1)
    coordination_capability: str = Field(default="", max_length=2048)
    coordination_fence: int | None = Field(default=None, ge=1)


class PolicyRequest(BaseModel):
    user_id: str
    token: str
    update: dict
    coordination_capability: str = Field(default="", max_length=2048)


class OwnerRequest(BaseModel):
    user_id: str
    token: str
    coordination_capability: str = Field(default="", max_length=2048)


class ImportRequest(BaseModel):
    user_id: str
    token: str
    files: list[dict]
    expected_revision: str | None = None
    coordination_capability: str = Field(default="", max_length=2048)
    coordination_fence: int | None = Field(default=None, ge=1)


class FileRequest(BaseModel):
    user_id: str
    token: str
    path: str = ""
    content: str | None = None
    pattern: str | None = None
    ref: str | None = None
    message: str | None = None
    expected_revision: str | None = None
    coordination_capability: str = Field(default="", max_length=2048)
    coordination_fence: int | None = Field(default=None, ge=1)


__all__ = [
    "CreateRequest",
    "ExecRequest",
    "FileRequest",
    "ImportRequest",
    "OwnerRequest",
    "PolicyRequest",
]
