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


class DocumentProjectRequest(OwnerRequest):
    path: str = Field(min_length=1, max_length=1024)
    profile_id: str = Field(min_length=3, max_length=64)
    mode: str = Field(default="draft", max_length=24)
    locale: str | None = Field(default=None, max_length=24)
    expected_revision: str = Field(min_length=1, max_length=128)
    coordination_fence: int | None = Field(default=None, ge=1)


class DocumentPathRequest(OwnerRequest):
    path: str = Field(min_length=1, max_length=1024)


class DocumentBuildRequest(DocumentPathRequest):
    expected_revision: str = Field(min_length=1, max_length=128)
    coordination_fence: int | None = Field(default=None, ge=1)
    final: bool = False


class DocumentProfileApplyRequest(DocumentPathRequest):
    target_path: str | None = Field(default=None, min_length=1, max_length=1024)
    profile_id: str = Field(min_length=3, max_length=64)
    mode: str | None = Field(default=None, pattern="^(draft|submission|camera_ready)$")
    locale: str | None = Field(default=None, max_length=24)
    expected_revision: str = Field(min_length=1, max_length=128)
    coordination_fence: int | None = Field(default=None, ge=1)


class DocumentVisualAuditResultRequest(OwnerRequest):
    source_digest: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    artifact_sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    passed: bool
    retryable: bool = False
    audit_version: int = Field(default=1, ge=1, le=100)
    diagnostics: list[dict] = Field(default_factory=list, max_length=100)
    coordination_fence: int | None = Field(default=None, ge=1)


class DocumentCancelRequest(OwnerRequest):
    coordination_fence: int | None = Field(default=None, ge=1)


__all__ = [
    "CreateRequest",
    "DocumentBuildRequest",
    "DocumentCancelRequest",
    "DocumentPathRequest",
    "DocumentProfileApplyRequest",
    "DocumentProjectRequest",
    "DocumentVisualAuditResultRequest",
    "ExecRequest",
    "FileRequest",
    "ImportRequest",
    "OwnerRequest",
    "PolicyRequest",
]
