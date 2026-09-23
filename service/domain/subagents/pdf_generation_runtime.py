"""Workspace authoring, build, audit and repair runtime for the PDF generator."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from service.domain.documents import (
    CitationRegistry,
    DocumentAuthoringCheckpoint,
    DocumentDraft,
    DocumentEvidenceBundle,
    DocumentIntent,
    DocumentStage,
    RenderedSourceBundle,
    audit_document_build,
    author_semantic_draft_result,
    literal_draft,
    render_document,
    repair_semantic_draft,
    restore_authoring_checkpoint,
)
from service.domain.tools.workspace_client import WorkspaceUnavailable, call
from service.shared import deadline

MAX_SOURCE_REPAIRS = 2
MAX_VISUAL_REPAIRS = 1
DocumentStageObserver = Callable[[DocumentStage, str], Awaitable[None]]


def can_retry_visual_failure(*, literal_text: str | None, visual_repairs: int) -> bool:
    """Allow one useful visual repair and never rebuild immutable literal source."""

    return literal_text is None and visual_repairs < MAX_VISUAL_REPAIRS


def authoring_model_meta(requested: str | None, actual: str | None) -> dict[str, str | None]:
    return {"requested_authoring_model": requested, "actual_authoring_model": actual}


def bind_evidence_policy(
    brief: DocumentIntent, citations: CitationRegistry | None
) -> DocumentIntent:
    if citations is None or brief.kind not in {"article", "report", "presentation"}:
        return brief
    return replace(brief, citation_policy="required")


def request_digest(value: str) -> str:
    return hashlib.sha256(str(value or "").strip().encode()).hexdigest()


async def _wait_build(ref: dict, build_id: str) -> dict[str, Any]:
    for _ in range(240):
        if deadline.must_finalize():
            return {"state": "failed", "failure_code": "build_timeout"}
        status = await call(ref, f"documents/builds/{build_id}", {})
        if status.get("state") in {
            "preview_ready",
            "visual_pending",
            "ready",
            "failed",
            "cancelled",
        }:
            return status
        await asyncio.sleep(0.5)
    return {"state": "failed", "failure_code": "build_timeout"}


def publication_artifacts(status: dict, *, initial_status: str) -> list[dict]:
    return [
        {
            "build_id": status.get("build_id"),
            "artifact_id": item.get("artifact_id"),
            "role": item.get("role"),
            "filename": item.get("filename"),
            "mime_type": item.get("mime_type"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
            "source_digest": status.get("source_digest"),
            "initial_status": initial_status,
        }
        for item in status.get("artifacts", [])
        if isinstance(item, dict)
        and item.get("artifact_id")
        and item.get("role") in {"pdf", "source_bundle"}
    ]


async def create_document_project(ref: dict, brief: DocumentIntent) -> tuple[str, str]:
    project_path = f"documents/document-{secrets.token_hex(4)}"
    created = await call(
        ref,
        "documents",
        {
            "path": project_path,
            "profile_id": brief.profile_id,
            "mode": brief.mode,
            "locale": brief.locale,
        },
    )
    if not created.get("revision"):
        raise WorkspaceUnavailable()
    scaffold_result = await call(ref, "files/read", {"path": f"{project_path}/main.tex"})
    scaffold_source = str(scaffold_result.get("content") or "")
    if "\\begin{document}" not in scaffold_source:
        raise WorkspaceUnavailable()
    return project_path, scaffold_source


async def _write_authored_source(
    ref: dict,
    project_path: str,
    authored: RenderedSourceBundle,
) -> None:
    result = await call(
        ref,
        "documents/source",
        {
            "path": project_path,
            "files": authored.files,
            "authoring_version": authored.authoring_version,
            "draft_digest": authored.draft_digest,
        },
    )
    if result.get("outcome") != "published":
        raise WorkspaceUnavailable()


async def _write_authoring_checkpoint(
    ref: dict,
    project_path: str,
    checkpoint: DocumentAuthoringCheckpoint,
    source_request_digest: str,
    evidence_digest: str,
) -> None:
    result = await call(
        ref,
        "documents/authoring/checkpoint",
        {
            "path": project_path,
            "checkpoint": checkpoint.payload(),
            "request_digest": source_request_digest,
            "evidence_digest": evidence_digest,
        },
    )
    if result.get("outcome") != "checkpointed":
        raise WorkspaceUnavailable()


async def resumable_document_project(
    ref: dict,
    *,
    source_request_digest: str,
    evidence: DocumentEvidenceBundle,
    citations: CitationRegistry | None,
) -> tuple[str, str, DocumentAuthoringCheckpoint] | None:
    result = await call(
        ref,
        "documents/authoring/checkpoint/latest",
        {"request_digest": source_request_digest, "evidence_digest": evidence.digest},
    )
    checkpoint = restore_authoring_checkpoint(
        result.get("checkpoint"),
        citations=citations,
        evidence=evidence,
    )
    project_path = str(result.get("path") or "")
    if checkpoint is None or not project_path:
        return None
    scaffold_result = await call(ref, "files/read", {"path": f"{project_path}/main.tex"})
    scaffold_source = str(scaffold_result.get("content") or "")
    if "\\begin{document}" not in scaffold_source:
        return None
    return project_path, scaffold_source, checkpoint


def _diagnostic_codes(status: dict[str, Any]) -> list[str]:
    return [
        (f"{str(item.get('code') or 'compile_failed')}:{str(item.get('block_id') or '')}").rstrip(
            ":"
        )
        for item in status.get("diagnostics", [])
        if isinstance(item, dict)
    ] or [str(status.get("failure_code") or "compile_failed")]


def _failure_stage(status: dict[str, Any] | None) -> DocumentStage:
    stage = str((status or {}).get("stage") or "")
    return {
        "intent": DocumentStage.INTENT,
        "evidence": DocumentStage.EVIDENCE,
        "outline": DocumentStage.OUTLINE,
        "section_authoring": DocumentStage.SECTION_AUTHORING,
        "source_publish": DocumentStage.SOURCE_PUBLISH,
        "compile": DocumentStage.COMPILE,
        "deterministic_audit": DocumentStage.DETERMINISTIC_AUDIT,
        "visual_audit": DocumentStage.VISUAL_AUDIT,
        "delivery": DocumentStage.DELIVERY,
    }.get(stage, DocumentStage.SECTION_AUTHORING)


def public_failure(status: dict[str, Any] | None) -> tuple[str, DocumentStage, bool]:
    """Map compiler internals to the closed document terminal contract."""

    code = str((status or {}).get("failure_code") or "internal")
    if code == "source_changed":
        return "source_conflict", DocumentStage.SOURCE_PUBLISH, True
    if code in {"audit_failed", "artifact_invalid"}:
        return "deterministic_audit_failed", DocumentStage.DETERMINISTIC_AUDIT, False
    if code == "visual_audit_failed":
        return "visual_audit_failed", DocumentStage.VISUAL_AUDIT, False
    if code in {"visual_unavailable", "visual_interrupted"}:
        return "visual_pending", DocumentStage.VISUAL_AUDIT, True
    if code == "build_cancelled":
        return "cancelled", DocumentStage.COMPILE, False
    if code in {
        "compile_failed",
        "build_timeout",
        "build_interrupted",
        "invalid_project",
        "artifact_too_large",
        "visual_render_failed",
        "runtime_unavailable",
    }:
        retryable = code in {"build_timeout", "build_interrupted", "runtime_unavailable"}
        return "compile_failed", DocumentStage.COMPILE, retryable
    if code in {
        "draft_protocol",
        "draft_invalid",
        "evidence_incomplete",
        "authoring_unsupported",
        "unresolved_requirements",
    }:
        return code, _failure_stage(status), False
    return "internal", _failure_stage(status), False


@dataclass(slots=True)
class DocumentGenerationRun:
    """Bounded source/build/audit loop, isolated from event projection."""

    ref: dict
    brief: DocumentIntent
    model: str
    project_path: str
    scaffold_source: str
    citations: CitationRegistry | None = None
    evidence: DocumentEvidenceBundle | None = None
    draft: DocumentDraft | None = None
    diagnostics: list[str] = field(default_factory=list)
    source_repairs: int = 0
    visual_repairs: int = 0
    authoring_repair_used: bool = False
    authoring_failure_stage: DocumentStage = DocumentStage.SECTION_AUTHORING
    authoring_rejection_reason: str | None = None
    accepted_sections: int = 0
    compile_started: bool = False
    source_request_digest: str = ""
    resume: DocumentAuthoringCheckpoint | None = None
    stage_observer: DocumentStageObserver | None = None

    async def _stage(self, stage: DocumentStage, status: str) -> None:
        if self.stage_observer is not None:
            await self.stage_observer(stage, status)

    async def _authoring_stage(self, stage: str) -> None:
        resolved = DocumentStage.OUTLINE if stage == "outline" else DocumentStage.SECTION_AUTHORING
        await self._stage(resolved, "running")

    async def _author(self, *, execution: Any) -> RenderedSourceBundle | None:
        if self.draft is None:
            if self.brief.literal_text is not None:
                self.draft = literal_draft(self.brief.literal_text)
            else:
                authored = await author_semantic_draft_result(
                    self.brief,
                    self.model,
                    execution=execution,
                    citations=self.citations,
                    evidence=self.evidence,
                    checkpoint=lambda value: _write_authoring_checkpoint(
                        self.ref,
                        self.project_path,
                        value,
                        self.source_request_digest,
                        self.evidence.digest if self.evidence is not None else "0" * 64,
                    ),
                    resume=self.resume,
                    stage=self._authoring_stage,
                )
                self.authoring_repair_used = authored.repair_used
                self.accepted_sections = authored.accepted_sections
                self.authoring_failure_stage = (
                    DocumentStage.OUTLINE
                    if authored.failure_stage == "outline"
                    else DocumentStage.SECTION_AUTHORING
                )
                self.authoring_rejection_reason = authored.rejection_reason
                self.draft = authored.draft
                self.resume = None
                if not authored.accepted:
                    self.diagnostics = [authored.failure_code or "draft_invalid"]
                    return None
        elif self.diagnostics:
            repaired = await repair_semantic_draft(
                self.brief,
                self.draft,
                self.diagnostics,
                self.model,
                execution=execution,
                citations=self.citations,
            )
            if repaired is None:
                return None
            self.draft = repaired
        if self.draft is None:
            return None
        bibliography = self.citations.bibliography() if self.citations else ""
        try:
            return render_document(
                self.brief,
                self.draft,
                scaffold_source=self.scaffold_source,
                citations=self.citations,
                bibliography=bibliography,
                enforce_evidence=False,
            )
        except ValueError as exc:
            code = str(exc)
            self.diagnostics = [
                code
                if code in {"citation_unknown", "evidence_required", "authoring_unsupported"}
                else "invalid_source"
            ]
            return None

    async def _compile(self, *, final: bool = True) -> dict[str, Any]:
        await self._stage(DocumentStage.COMPILE, "running")
        self.compile_started = True
        started = await call(
            self.ref,
            "documents/builds",
            {"path": self.project_path, "final": final},
        )
        build_id = str(started.get("build_id") or "")
        if not build_id:
            raise WorkspaceUnavailable()
        return await _wait_build(self.ref, build_id)

    async def _resolve_visual_audit(
        self,
        status: dict[str, Any],
        *,
        execution: Any,
    ) -> tuple[dict[str, Any], bool]:
        await self._stage(DocumentStage.DETERMINISTIC_AUDIT, "ready")
        await self._stage(DocumentStage.VISUAL_AUDIT, "running")
        build_id = str(status.get("build_id") or "")
        audit = await audit_document_build(self.ref, build_id, execution=execution)
        if audit.passed:
            await self._stage(DocumentStage.VISUAL_AUDIT, "ready")
            return await call(self.ref, f"documents/builds/{build_id}", {}), True
        if audit.retryable:
            await self._stage(DocumentStage.VISUAL_AUDIT, "pending")
            return {**status, "failure_code": audit.status}, False
        audited = await call(self.ref, f"documents/builds/{build_id}", {})
        visual_failed = (
            audited.get("state") == "failed"
            and audited.get("failure_code") == "visual_audit_failed"
        )
        can_repair = visual_failed and can_retry_visual_failure(
            literal_text=self.brief.literal_text,
            visual_repairs=self.visual_repairs,
        )
        if can_repair:
            self.visual_repairs += 1
        await self._stage(DocumentStage.VISUAL_AUDIT, "failed")
        return audited, bool(not visual_failed or can_repair)

    async def _preview_blocked_final(
        self,
        failure_code: str,
    ) -> dict[str, Any]:
        preview = await self._compile(final=False)
        preview_ready = preview.get("state") == "preview_ready"
        if preview_ready:
            await self._stage(DocumentStage.DETERMINISTIC_AUDIT, "ready")
        return {
            **preview,
            "state": "draft_ready" if preview_ready else preview.get("state", "failed"),
            "stage": "evidence",
            "failure_code": (
                failure_code if preview_ready else preview.get("failure_code", "compile_failed")
            ),
            "project_saved": True,
        }

    async def execute(self, *, execution: Any) -> dict[str, Any] | None:
        final_status: dict[str, Any] | None = None
        for _attempt in range(1 + MAX_SOURCE_REPAIRS + MAX_VISUAL_REPAIRS):
            authored = await self._author(execution=execution)
            if authored is None:
                if final_status is not None:
                    # A bounded source/visual repair is optional.  If the model
                    # cannot produce a valid patch, retain the verified build
                    # failure that caused the repair instead of relabelling it
                    # as an initial authoring failure.
                    return final_status
                return {
                    "state": "failed",
                    "stage": self.authoring_failure_stage.value,
                    "failure_code": self.diagnostics[0] if self.diagnostics else "draft_invalid",
                    "project_saved": True,
                    "authoring_repair_used": self.authoring_repair_used,
                    "accepted_sections": self.accepted_sections,
                    "authoring_rejection_reason": self.authoring_rejection_reason,
                }
            await self._stage(DocumentStage.SOURCE_PUBLISH, "running")
            await _write_authored_source(self.ref, self.project_path, authored)
            await self._stage(DocumentStage.SOURCE_PUBLISH, "ready")
            if self.brief.requires_bibliography and (
                self.citations is None or self.draft is None or not self.draft.cited_source_ids
            ):
                return await self._preview_blocked_final("evidence_incomplete")
            if self.brief.requires_placeholders:
                return await self._preview_blocked_final("unresolved_requirements")
            final_status = await self._compile()
            final_status = {**final_status, "stage": "compile", "project_saved": True}
            may_repair = True
            if final_status.get("state") == "visual_pending":
                final_status, may_repair = await self._resolve_visual_audit(
                    final_status,
                    execution=execution,
                )
            elif final_status.get("failure_code") in {"audit_failed", "artifact_invalid"}:
                await self._stage(DocumentStage.DETERMINISTIC_AUDIT, "failed")
            if final_status.get("state") == "ready" or not may_repair:
                break
            visual_failure = (
                final_status.get("state") == "failed"
                and final_status.get("failure_code") == "visual_audit_failed"
            )
            if not visual_failure:
                if self.source_repairs >= MAX_SOURCE_REPAIRS:
                    break
                self.source_repairs += 1
            self.diagnostics = _diagnostic_codes(final_status)
            if self.diagnostics[0] in {"source_changed", "build_cancelled", "build_timeout"}:
                break
        return final_status


__all__ = [
    "DocumentGenerationRun",
    "authoring_model_meta",
    "bind_evidence_policy",
    "create_document_project",
    "public_failure",
    "publication_artifacts",
    "request_digest",
    "resumable_document_project",
]
