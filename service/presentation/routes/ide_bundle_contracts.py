"""Strict technical bounds shared by private capsule capture and restoration."""

from pydantic import BaseModel, ConfigDict, Field


class CaptureLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entries: int = Field(ge=1, le=65533)
    file_bytes: int = Field(ge=1, lt=2**31)
    total_bytes: int = Field(ge=1, lt=2**31)
    archive_bytes: int = Field(ge=1, lt=2**31)
    manifest_bytes: int = Field(ge=1, le=16 * 1024 * 1024)
    depth: int = Field(ge=1, le=64)
