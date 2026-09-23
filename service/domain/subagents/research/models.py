"""Research plan, progress, evidence, and result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ResearchStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    NO_SOURCES = "no_sources"
    FAILED = "failed"
    DEADLINE = "deadline"


@dataclass(frozen=True, slots=True)
class ResearchProgress:
    progress: int
    label: str
    detail: list[str] = field(default_factory=list)
    stage: str = "research"
    status: str = "running"
    failure_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "progress", max(0, min(100, int(self.progress))))
        object.__setattr__(self, "label", str(self.label or "")[:160])
        # Compatibility retains detail in-process. New pipeline only places bounded
        # counters here, never queries, URLs, snippets, or exception text.
        object.__setattr__(self, "detail", [str(item)[:80] for item in self.detail[:20]])

    def bounded_metadata(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "stage": self.stage,
            "progress": self.progress,
            "status": self.status,
            "detail_count": len(self.detail),
        }
        if self.failure_code:
            data["failure_code"] = self.failure_code
        return data


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    queries: tuple[str, ...]
    fallback: bool = False

    @property
    def query_count(self) -> int:
        return len(self.queries)


@dataclass(frozen=True, slots=True)
class CollectionStats:
    query_count: int = 0
    result_count: int = 0
    source_count: int = 0
    read_failures: int = 0
    search_failures: int = 0
    deadline_stops: int = 0

    @property
    def partial(self) -> bool:
        return bool(self.read_failures or self.search_failures or self.deadline_stops)

    def bounded_metadata(self) -> dict[str, int]:
        return {
            "query_count": self.query_count,
            "result_count": self.result_count,
            "source_count": self.source_count,
            "read_failures": self.read_failures,
            "search_failures": self.search_failures,
            "deadline_stops": self.deadline_stops,
        }


@dataclass(frozen=True, slots=True)
class ResearchReport:
    body: str
    sources_section: str
    status: ResearchStatus
    collection: CollectionStats
    citation_valid: bool = False
    repair_used: bool = False

    @property
    def text(self) -> str:
        body = self.body.rstrip()
        sources = self.sources_section.rstrip()
        if body and sources:
            return f"{body}\n\n---\n\n{sources}\n"
        return body or sources


__all__ = [
    "CollectionStats",
    "ResearchPlan",
    "ResearchProgress",
    "ResearchReport",
    "ResearchStatus",
]
