"""Internal backend-to-agents contract for the autonomous workflow projection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WorkflowCatalogUpsertRequest(BaseModel):
    point_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    label_ru: str = Field(min_length=1, max_length=300)
    steps: list[str] = Field(min_length=1, max_length=16)
    cost_class: str = Field(min_length=1, max_length=32)
    state: str = Field(min_length=1, max_length=32)
    quality_score: float = Field(ge=0.0, le=1.0)
    reuse_score: float = Field(ge=0.0, le=1.0)
    # Used only to calculate the embedding; catalog.py never places it in payload/logs.
    request_text: str = Field(min_length=1, max_length=65536)

    model_config = ConfigDict(extra="forbid")


class WorkflowCatalogDeleteRequest(BaseModel):
    point_id: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(extra="forbid")
