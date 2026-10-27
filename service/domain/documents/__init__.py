"""Document Forge brief, skill and source contracts."""

from service.domain.documents.authoring.execution import (
    DocumentAuthoringCheckpoint,
    DocumentAuthoringResult,
    author_semantic_draft,
    author_semantic_draft_result,
    repair_semantic_draft,
    resolve_document_intent,
    restore_authoring_checkpoint,
)
from service.domain.documents.evidence.bundle import (
    DocumentEvidenceBundle,
    build_document_evidence_bundle,
)
from service.domain.documents.evidence.citations import CitationRegistry
from service.domain.documents.semantic.draft import (
    DocumentDraft,
    DraftBlock,
    DraftPatch,
    apply_draft_patch,
    literal_draft,
    parse_document_draft,
    parse_draft_patch,
)
from service.domain.documents.semantic.rendering import RenderedSourceBundle, render_document
from service.domain.documents.skills.catalog import DOCUMENT_SKILL_CATALOG, DocumentSkillCatalog
from service.domain.documents.skills.contracts import DocumentSkill, skill_for_profile
from service.domain.documents.skills.profiles import (
    DOCUMENT_PROFILE_CONTRACT_VERSION,
    DOCUMENT_PROFILE_IDS,
)

from .brief import DocumentBrief, normalize_brief
from .intent import DocumentIntent, deterministic_intent, literal_shortcut, parse_document_intent
from .run_outcome import DocumentRunOutcome, DocumentStage, document_status_event
from .source import (
    AuthoredDocument,
    parse_authored_document,
    parse_authored_tool_response,
    render_literal_document,
)
from .visual_audit import VisualAuditResult, audit_document_build

__all__ = [
    "AuthoredDocument",
    "DocumentBrief",
    "DocumentDraft",
    "DocumentAuthoringCheckpoint",
    "DocumentAuthoringResult",
    "DocumentEvidenceBundle",
    "DocumentIntent",
    "DocumentSkill",
    "DocumentSkillCatalog",
    "DraftBlock",
    "DraftPatch",
    "CitationRegistry",
    "DOCUMENT_SKILL_CATALOG",
    "VisualAuditResult",
    "DOCUMENT_PROFILE_CONTRACT_VERSION",
    "DOCUMENT_PROFILE_IDS",
    "normalize_brief",
    "author_semantic_draft",
    "author_semantic_draft_result",
    "build_document_evidence_bundle",
    "repair_semantic_draft",
    "restore_authoring_checkpoint",
    "resolve_document_intent",
    "deterministic_intent",
    "literal_shortcut",
    "parse_document_intent",
    "parse_document_draft",
    "parse_draft_patch",
    "apply_draft_patch",
    "literal_draft",
    "RenderedSourceBundle",
    "render_document",
    "DocumentRunOutcome",
    "DocumentStage",
    "document_status_event",
    "parse_authored_document",
    "parse_authored_tool_response",
    "render_literal_document",
    "skill_for_profile",
    "audit_document_build",
]
