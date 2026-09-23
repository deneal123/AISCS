"""Request contracts for chat-scoped workspace routes."""

from pydantic import BaseModel, Field


class PathRequest(BaseModel):
    path: str = Field(default="", max_length=1024)


class RevertRequest(BaseModel):
    ref: str = Field(..., min_length=1, max_length=64)
    expected_revision: str = Field(..., min_length=1, max_length=64)
    path: str = Field(default="", max_length=1024)


class DiffRequest(BaseModel):
    ref: str = Field(..., min_length=1, max_length=64)
    path: str = Field(default="", max_length=1024)


class WriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(..., max_length=1_000_000)
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int | None = Field(default=None, ge=1)


class LeaseRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    fence: int | None = Field(default=None, ge=1)


class LibraryCopyRequest(BaseModel):
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class IssueCreateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    start_line: int = Field(..., ge=1, le=1_000_000)
    end_line: int = Field(..., ge=1, le=1_000_000)
    revision: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=180)
    body: str = Field(default="", max_length=4_000)


class IssueUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|resolved|stale)$")
    revision: str | None = Field(default=None, max_length=64)
    start_line: int | None = Field(default=None, ge=1, le=1_000_000)
    end_line: int | None = Field(default=None, ge=1, le=1_000_000)


class ControlRequest(BaseModel):
    action: str = Field(..., pattern="^(pause|resume|cancel)$")


class DocumentProjectRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    profile_id: str = Field(..., min_length=3, max_length=64)
    mode: str = Field(default="draft", pattern="^(draft|submission|camera_ready)$")
    locale: str | None = Field(default=None, max_length=24)
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class DocumentPathRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)


class DocumentBuildRequest(DocumentPathRequest):
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)
    final: bool = False


class DocumentSourceRequest(DocumentPathRequest):
    files: dict[str, str] = Field(..., min_length=1, max_length=128)
    authoring_version: int = Field(..., ge=1, le=1_000_000)
    draft_digest: str = Field(..., pattern="^[0-9a-f]{64}$")
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class DocumentProfileApplyRequest(DocumentPathRequest):
    target_path: str = Field(..., min_length=1, max_length=1024)
    profile_id: str = Field(..., min_length=3, max_length=64)
    mode: str | None = Field(default=None, pattern="^(draft|submission|camera_ready)$")
    locale: str | None = Field(default=None, max_length=24)
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class DocumentVendorOverlayRequest(DocumentPathRequest):
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class DocumentVendorActivateRequest(DocumentPathRequest):
    target_path: str = Field(..., min_length=1, max_length=1024)
    expected_revision: str = Field(..., min_length=1, max_length=64)
    fence: int = Field(..., ge=1)


class DocumentCancelRequest(BaseModel):
    fence: int = Field(..., ge=1)
