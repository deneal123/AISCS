"""Evidence-first research pipeline with deterministic citation safety."""

from .audit import CitationAudit, audit_citations
from .models import ResearchProgress, ResearchReport
from .pipeline import ResearchDependencies, run_native_research
from .sources import ResearchArtifact, SourceRecord, SourceRegistry, artifact_from_external_sources

__all__ = [
    "CitationAudit",
    "ResearchDependencies",
    "ResearchProgress",
    "ResearchReport",
    "ResearchArtifact",
    "SourceRecord",
    "SourceRegistry",
    "artifact_from_external_sources",
    "audit_citations",
    "run_native_research",
]
