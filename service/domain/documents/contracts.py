"""Immutable internal contracts for LaTeX document projects and builds."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal

DOCUMENT_KINDS = frozenset({"article", "presentation", "legal", "report", "generic"})
ENGINES = frozenset({"pdflatex", "xelatex", "lualatex"})
BUILD_MODES = frozenset({"draft", "submission", "camera_ready"})
BUILD_STATES = frozenset(
    {
        "queued",
        "preparing",
        "building",
        "deterministic_audit",
        "visual_pending",
        "visual_audit",
        "publishing",
        "preview_ready",
        "ready",
        "failed",
        "cancelled",
    }
)
DIAGNOSTIC_SEVERITIES = frozenset({"info", "warning", "error"})
ARTIFACT_ROLES = frozenset({"pdf", "source_bundle", "thumbnail", "report"})


def _validate_manifest_types(raw: dict[str, object]) -> None:
    """Reject corrupt persisted values before coercion can change their meaning."""
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        raise ValueError("unsupported build manifest")
    if "final" in raw and type(raw["final"]) is not bool:
        raise ValueError("invalid build manifest")
    if "mode" in raw and (not isinstance(raw["mode"], str) or raw["mode"] not in BUILD_MODES):
        raise ValueError("invalid build manifest")
    for key in (
        "profile_version",
        "authoring_version",
        "page_count",
        "visual_bundle_size",
        "visual_audit_version",
    ):
        if key not in raw:
            continue
        value = raw[key]
        minimum = 1 if key == "profile_version" else 0
        if type(value) is not int or not minimum <= value <= 2**53 - 1:
            raise ValueError("invalid build manifest")
    for key in (
        "created_at",
        "completed_at",
        "visual_audit_claimed_at",
        "page_width_pt",
        "page_height_pt",
    ):
        if key not in raw:
            continue
        value = raw[key]
        if value is None and key in {"completed_at", "visual_audit_claimed_at"}:
            continue
        if (
            type(value) not in {int, float}
            or not 0 <= value <= 2**53 - 1
            or not math.isfinite(value)
        ):
            raise ValueError("invalid build manifest")


BuildState = Literal[
    "queued",
    "preparing",
    "building",
    "deterministic_audit",
    "visual_pending",
    "visual_audit",
    "publishing",
    "preview_ready",
    "ready",
    "failed",
    "cancelled",
]


@dataclass(frozen=True, slots=True)
class DocumentProfile:
    profile_id: str
    version: int
    label_ru: str
    kind: str
    engine: str
    entrypoint: str
    documentclass: str
    locale: str
    paper: str
    orientation: str
    bibliography_backend: str
    bibliography_required: bool
    required_sections: tuple[str, ...]
    locked_fields: frozenset[str]
    allowed_overrides: frozenset[str]
    anonymize_supported: bool
    source_export: str
    max_pages: int | None
    content_contract: str
    template_dir: str
    digest: str

    def __post_init__(self) -> None:
        if self.kind not in DOCUMENT_KINDS:
            raise ValueError("invalid document kind")
        if self.engine not in ENGINES:
            raise ValueError("invalid document engine")
        if self.bibliography_backend not in {"none", "bibtex", "biber"}:
            raise ValueError("invalid bibliography backend")
        if self.source_export not in {"allowed", "required", "forbidden"}:
            raise ValueError("invalid source export policy")
        if (
            not self.profile_id
            or self.version < 1
            or not self.entrypoint.endswith(".tex")
            or not self.documentclass
        ):
            raise ValueError("invalid document profile identity")

    @property
    def versioned_id(self) -> str:
        return f"{self.profile_id}@{self.version}"

    def public_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "label": self.label_ru,
            "kind": self.kind,
            "engine": self.engine,
            "locale": self.locale,
            "paper": self.paper,
            "orientation": self.orientation,
            "bibliography_required": self.bibliography_required,
            "anonymize_supported": self.anonymize_supported,
            "source_export": self.source_export,
            "allowed_overrides": sorted(self.allowed_overrides),
            "content_contract": self.content_contract,
        }


@dataclass(frozen=True, slots=True)
class DocumentDiagnostic:
    severity: str
    code: str
    relative_path: str = ""
    line: int | None = None
    count: int = 1
    block_id: str = ""

    def public_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity if self.severity in DIAGNOSTIC_SEVERITIES else "error",
            "code": self.code,
            **({"path": self.relative_path} if self.relative_path else {}),
            **({"line": self.line} if self.line is not None else {}),
            "count": max(1, self.count),
            **({"block_id": self.block_id} if self.block_id else {}),
        }


@dataclass(frozen=True, slots=True)
class DocumentArtifact:
    artifact_id: str
    role: str
    filename: str
    mime_type: str
    size: int
    sha256: str
    internal_path: str = field(repr=False)

    def public_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "role": self.role if self.role in ARTIFACT_ROLES else "report",
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": max(0, self.size),
            "sha256": self.sha256,
        }


@dataclass(slots=True)
class DocumentBuild:
    build_id: str
    workspace_id: str
    project_path: str
    profile_id: str
    profile_version: int
    source_revision: str
    source_digest: str
    mode: str
    final: bool
    authoring_version: int = 0
    draft_digest: str = ""
    output_revision: str = ""
    state: BuildState = "queued"
    failure_code: str = ""
    page_count: int = 0
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0
    diagnostics: tuple[DocumentDiagnostic, ...] = ()
    artifacts: tuple[DocumentArtifact, ...] = ()
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    compiler_ref: str = field(default="", repr=False)
    visual_bundle_path: str = field(default="", repr=False)
    visual_bundle_sha256: str = field(default="", repr=False)
    visual_bundle_size: int = field(default=0, repr=False)
    visual_audit_version: int = 0
    visual_audit_claimed_at: float | None = field(default=None, repr=False)
    page_blocks: dict[int, tuple[str, ...]] = field(default_factory=dict, repr=False)
    manifest_uncertain: bool = field(default=False, repr=False)

    @property
    def terminal(self) -> bool:
        return self.state in {"preview_ready", "ready", "failed", "cancelled"}

    @property
    def recoverable(self) -> bool:
        return self.state in {"visual_pending", "preview_ready", "ready", "failed", "cancelled"}

    def manifest_dict(self) -> dict[str, object]:
        """Private restart record; never returned by an HTTP route."""

        return {
            "schema_version": 1,
            "build_id": self.build_id,
            "workspace_id": self.workspace_id,
            "project_path": self.project_path,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "source_revision": self.source_revision,
            "source_digest": self.source_digest,
            "authoring_version": self.authoring_version,
            "draft_digest": self.draft_digest,
            "mode": self.mode,
            "final": self.final,
            "output_revision": self.output_revision,
            "state": self.state,
            "failure_code": self.failure_code,
            "page_count": self.page_count,
            "page_width_pt": self.page_width_pt,
            "page_height_pt": self.page_height_pt,
            "diagnostics": [item.public_dict() for item in self.diagnostics],
            "artifacts": [
                {**item.public_dict(), "internal_path": item.internal_path}
                for item in self.artifacts
            ],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "compiler_ref": self.compiler_ref,
            "visual_bundle_path": self.visual_bundle_path,
            "visual_bundle_sha256": self.visual_bundle_sha256,
            "visual_bundle_size": self.visual_bundle_size,
            "visual_audit_version": self.visual_audit_version,
            "visual_audit_claimed_at": self.visual_audit_claimed_at,
            "page_blocks": {
                str(page): list(blocks) for page, blocks in sorted(self.page_blocks.items())
            },
        }

    @classmethod
    def from_manifest(cls, raw: dict[str, object]) -> DocumentBuild:
        _validate_manifest_types(raw)
        state = str(raw.get("state") or "")
        if state not in BUILD_STATES:
            raise ValueError("invalid build state")
        diagnostics = tuple(
            DocumentDiagnostic(
                severity=str(item.get("severity") or "error"),
                code=str(item.get("code") or "internal")[:64],
                relative_path=str(item.get("path") or "")[:1024],
                line=(int(item["line"]) if isinstance(item.get("line"), int) else None),
                count=max(1, int(item.get("count") or 1)),
                block_id=str(item.get("block_id") or "")[:64],
            )
            for item in raw.get("diagnostics", [])
            if isinstance(item, dict)
        )
        artifacts = tuple(
            DocumentArtifact(
                artifact_id=str(item.get("artifact_id") or ""),
                role=str(item.get("role") or "report"),
                filename=str(item.get("filename") or "artifact")[:255],
                mime_type=str(item.get("mime_type") or "application/octet-stream")[:128],
                size=max(0, int(item.get("size") or 0)),
                sha256=str(item.get("sha256") or ""),
                internal_path=str(item.get("internal_path") or ""),
            )
            for item in raw.get("artifacts", [])
            if isinstance(item, dict)
        )
        build = cls(
            build_id=str(raw.get("build_id") or ""),
            workspace_id=str(raw.get("workspace_id") or ""),
            project_path=str(raw.get("project_path") or ""),
            profile_id=str(raw.get("profile_id") or ""),
            profile_version=max(1, int(raw.get("profile_version") or 1)),
            source_revision=str(raw.get("source_revision") or ""),
            source_digest=str(raw.get("source_digest") or ""),
            mode=str(raw.get("mode") or "draft"),
            final=bool(raw.get("final")),
            authoring_version=max(0, int(raw.get("authoring_version") or 0)),
            draft_digest=str(raw.get("draft_digest") or ""),
            output_revision=str(raw.get("output_revision") or ""),
            state=state,  # type: ignore[arg-type]
            failure_code=str(raw.get("failure_code") or "")[:64],
            page_count=max(0, int(raw.get("page_count") or 0)),
            page_width_pt=max(0.0, float(raw.get("page_width_pt") or 0.0)),
            page_height_pt=max(0.0, float(raw.get("page_height_pt") or 0.0)),
            diagnostics=diagnostics[:100],
            artifacts=artifacts[:8],
            created_at=float(raw.get("created_at") or time.time()),
            completed_at=(
                float(raw["completed_at"])
                if isinstance(raw.get("completed_at"), (int, float))
                else None
            ),
            compiler_ref=str(raw.get("compiler_ref") or ""),
            visual_bundle_path=str(raw.get("visual_bundle_path") or ""),
            visual_bundle_sha256=str(raw.get("visual_bundle_sha256") or ""),
            visual_bundle_size=max(0, int(raw.get("visual_bundle_size") or 0)),
            visual_audit_version=max(0, int(raw.get("visual_audit_version") or 0)),
            visual_audit_claimed_at=(
                float(raw["visual_audit_claimed_at"])
                if isinstance(raw.get("visual_audit_claimed_at"), (int, float))
                else None
            ),
            page_blocks={
                int(page): tuple(
                    str(block_id)[:64]
                    for block_id in blocks
                    if isinstance(block_id, str) and 3 <= len(block_id) <= 64
                )
                for page, blocks in (
                    raw.get("page_blocks", {}).items()
                    if isinstance(raw.get("page_blocks"), dict)
                    else []
                )
                if str(page).isdigit() and 1 <= int(page) <= 200 and isinstance(blocks, list)
            },
        )
        if (
            not build.build_id
            or not build.workspace_id
            or len(build.source_digest) != 64
            or any(not artifact.artifact_id for artifact in build.artifacts)
        ):
            raise ValueError("invalid build manifest")
        return build

    def public_dict(self) -> dict[str, object]:
        return {
            "build_id": self.build_id,
            "state": self.state,
            "failure_code": self.failure_code or None,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "source_revision": self.source_revision,
            "source_digest": self.source_digest,
            "authoring_version": self.authoring_version,
            "draft_digest": self.draft_digest or None,
            "output_revision": self.output_revision or self.source_revision,
            "mode": self.mode,
            "final": self.final,
            "page_count": self.page_count,
            "page_size_pt": {
                "width": self.page_width_pt,
                "height": self.page_height_pt,
            },
            "diagnostics": [item.public_dict() for item in self.diagnostics],
            "artifacts": [item.public_dict() for item in self.artifacts],
            "visual_audit_version": self.visual_audit_version,
        }
