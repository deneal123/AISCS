"""Local stdio MCP transport for the research knowledge base."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .contracts import SERVICE_VERSION
from .core import DataError, ResearchRepository, default_data_dir
from .curation import cluster_apply, cluster_check, review_apply, review_check
from .integrity import validate_repository
from .novelty import search_novelty as search_novelty_catalogue
from .pipeline import atomic_write_json, publish_candidates, review_candidates, snapshot_repository

SERVER_INSTRUCTIONS = (
    "This server manages the local Aspa dissertation evidence registry. Simulation labels are "
    "not subjective pain; ECAP is not a direct measure of pain; verified_primary confirms the "
    "primary source was checked, not that its claims were independently reproduced. Keep "
    "Drosophila simulation, transfer to human pain datasets, and clinical SCS validation as "
    "separate evidence levels. The required bridge uses a Drosophila dynamics model and a "
    "separate physical human ECAP observation model; the fly is not a direct digital twin of "
    "the human spinal cord. Mutating tools require an explicit apply=true where offered."
)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _bounded_page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= 200:
        raise DataError("limit must be between 1 and 200")
    if offset < 0:
        raise DataError("offset must be non-negative")
    return limit, offset


def _safe_name(value: str, *, suffix: str | None = None) -> str:
    name = value.strip()
    if not SAFE_NAME.fullmatch(name) or Path(name).name != name:
        raise DataError("name must contain only letters, digits, dot, underscore, or hyphen")
    if suffix and not name.endswith(suffix):
        name += suffix
    return name


def _within(path: Path, directory: Path) -> Path:
    resolved = path.resolve()
    base = directory.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise DataError(f"path must stay inside {base}") from exc
    return resolved


class ResearchMcpService:
    """Bounded MCP-facing operations over the existing repository and pipelines."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir).resolve() if data_dir else default_data_dir()
        self.project_dir = self.data_dir.parent
        self.repository = ResearchRepository(self.data_dir)
        from .knowledge.engine import KnowledgeEngine

        self.knowledge = KnowledgeEngine(self.repository)

    def status(self) -> dict[str, Any]:
        integrity = validate_repository(self.data_dir)
        return {
            "service_version": SERVICE_VERSION,
            "fingerprint": self.repository.bundle().fingerprint,
            "counts": integrity.get("counts", {}),
            "evidence_summary": self.repository.evidence_summary(),
            "integrity": {
                "ok": integrity["ok"],
                "errors": integrity["errors"],
                "warnings": integrity["warnings"],
            },
        }

    def search_sources(self, **kwargs: Any) -> dict[str, Any]:
        limit, offset = _bounded_page(kwargs.pop("limit", 50), kwargs.pop("offset", 0))
        return self.repository.list_sources(limit=limit, offset=offset, **kwargs)

    def get_source_context(self, source_id: str) -> dict[str, Any]:
        result = self.repository.get_source_context(source_id)
        if result is None:
            raise DataError(f"source not found: {source_id}")
        return result

    def search_resources(
        self,
        query: str | None = None,
        validation_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = _bounded_page(limit, offset)
        return self.repository.list_resources(
            query=query,
            validation_status=validation_status,
            limit=limit,
            offset=offset,
        )

    def get_cluster(self, cluster_id: str, expand_sources: bool = False) -> dict[str, Any]:
        result = self.repository.get_cluster_context(cluster_id, expand_sources=expand_sources)
        if result is None:
            raise DataError(f"cluster not found: {cluster_id}")
        return result

    def search_evidence(
        self,
        query: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = _bounded_page(limit, offset)
        return self.repository.list_evidence(
            query=query, source_id=source_id, limit=limit, offset=offset
        )

    def search_novelty(
        self,
        query: str | None = None,
        prior_art_outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        limit, offset = _bounded_page(limit, offset)
        return search_novelty_catalogue(
            self.data_dir,
            query=query,
            prior_art_outcome=prior_art_outcome,
            limit=limit,
            offset=offset,
        )

    def get_dissertation_concept(self) -> dict[str, Any]:
        return self.repository.dissertation_concept()

    def save_candidate(
        self, filename: str, candidate: dict[str, Any] | list[Any]
    ) -> dict[str, Any]:
        name = _safe_name(filename, suffix=".json")
        inbox = self.data_dir / "staging" / "inbox"
        destination = _within(inbox / name, inbox)
        if destination.exists():
            raise DataError(f"candidate already exists; overwrite is not allowed: {name}")
        inbox.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=inbox,
                prefix=".mcp-review-",
                suffix=".json",
                delete=False,
            ) as handle:
                json.dump(candidate, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                temporary_path = Path(handle.name)
            review = review_candidates(self.data_dir, temporary_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        if not review["ok"]:
            return {key: value for key, value in review.items() if key != "candidates"} | {
                "saved": False
            }
        atomic_write_json(destination, candidate)
        return {
            "ok": True,
            "saved": True,
            "path": str(destination.relative_to(self.data_dir)),
            "candidate_ids": review["candidate_ids"],
            "warnings": review["warnings"],
        }

    def _candidate_path(self, filename: str) -> Path:
        name = _safe_name(filename, suffix=".json")
        path = _within(self.data_dir / "staging" / "inbox" / name, self.data_dir / "staging")
        if not path.is_file():
            raise DataError(f"candidate not found: {name}")
        return path

    def publish_candidate(self, filename: str, *, apply: bool = False) -> dict[str, Any]:
        return publish_candidates(self.data_dir, self._candidate_path(filename), apply=apply)

    def _review_batch_path(self, batch: str) -> str:
        if Path(batch).name != batch or not SAFE_NAME.fullmatch(batch):
            raise DataError("review batch must be a batch name, not a path")
        return batch

    def review_batch(self, batch: str, *, apply: bool = False) -> dict[str, Any]:
        path = self._review_batch_path(batch)
        return (
            review_apply(self.data_dir, path, apply=True)
            if apply
            else review_check(self.data_dir, path)
        )

    def _cluster_manifest_path(self, manifest: str) -> Path:
        name = _safe_name(manifest, suffix=".json")
        base = self.data_dir / "curation" / "cluster-assignments"
        path = _within(base / name, base)
        if not path.is_file():
            raise DataError(f"cluster manifest not found: {name}")
        return path

    def cluster_manifest(self, manifest: str, *, apply: bool = False) -> dict[str, Any]:
        path = self._cluster_manifest_path(manifest)
        return (
            cluster_apply(self.data_dir, path, apply=True)
            if apply
            else cluster_check(self.data_dir, path)
        )

    def snapshot(self, label: str) -> dict[str, Any]:
        safe_label = _safe_name(label)
        path = snapshot_repository(self.data_dir, label=safe_label, persistent=True)
        return {"ok": True, "snapshot": str(path), "manifest": str(path / "manifest.json")}

    def read_text(self, relative_path: str) -> str:
        allowed = {
            "knowledge/README.md",
            "knowledge/corpus-manifest.json",
            "README.md",
            "TODO.md",
            "data/audits/summary/audit-report.json",
            "data/evidence/evidence-matrix.json",
            "docs/scientific-contract.md",
            "docs/README.md",
            "docs/final-validation-report.md",
            "docs/audits/README.md",
            "docs/audits/todo-decision-ledger.md",
            "docs/reference/operations.md",
            "docs/audits/evd03-evidence-matrix-audit-2026-09-25.md",
            "data/evidence/human-dataset-matrix.json",
            "data/schema/source-record.schema.json",
            "data/schema/vocabularies.json",
            "data/audits/summary/completeness-report.json",
            "data/audits/search/search-protocol.json",
            "data/research/novelty-landscape.json",
            "data/research/dissertation-concept.json",
            "data/audits/drosophila/runtime-audit.json",
            "docs/novelty-landscape.md",
            "docs/dissertation-concept.md",
        }
        if relative_path not in allowed:
            raise DataError("resource is not allowlisted")
        return (self.project_dir / relative_path).read_text(encoding="utf-8")

    def source_resource(self, source_id: str) -> str:
        return json.dumps(self.get_source_context(source_id), ensure_ascii=False, indent=2)

    def cluster_resource(self, cluster_id: str) -> str:
        return json.dumps(
            self.get_cluster(cluster_id, expand_sources=False),
            ensure_ascii=False,
            indent=2,
        )


def create_server(data_dir: Path | str | None = None) -> MCPServer:
    service = ResearchMcpService(data_dir)
    server = MCPServer(
        "aspa-research",
        version=SERVICE_VERSION,
        instructions=SERVER_INSTRUCTIONS,
        log_level="WARNING",
    )

    @server.tool(annotations=READ_ONLY)
    def status() -> dict[str, Any]:
        """Return corpus fingerprint, counters, evidence summary, and integrity gate."""
        return service.status()

    @server.tool(annotations=READ_ONLY)
    def knowledge_status() -> dict[str, Any]:
        """Return active graph/vector generation, coverage and review gaps."""
        return service.knowledge.status()

    @server.tool(annotations=READ_ONLY)
    def search_knowledge(
        query: str,
        filters: dict | None = None,
        mode: str = "hybrid",
        limit: int = 10,
        include_unreviewed: bool = False,
    ) -> dict[str, Any]:
        """Retrieve sourced evidence with limitations; similarity is not scientific proof."""
        return service.knowledge.search(
            query, filters=filters, mode=mode, limit=limit, include_unreviewed=include_unreviewed
        )

    @server.tool(annotations=READ_ONLY)
    def graph_context(
        node_id: str,
        depth: int = 1,
        edge_types: list[str] | None = None,
        include_unreviewed: bool = False,
    ) -> dict[str, Any]:
        """Expand typed, provenance-carrying links up to two hops."""
        return service.knowledge.graph(
            node_id, depth=depth, edge_types=edge_types, include_unreviewed=include_unreviewed
        )

    @server.tool(annotations=READ_ONLY)
    def get_evidence(node_id: str, include_unreviewed: bool = False) -> dict[str, Any]:
        """Get exact evidence text, primary locators and scientific restrictions."""
        return service.knowledge.evidence(node_id, include_unreviewed=include_unreviewed)

    @server.tool(annotations=READ_ONLY)
    def search_sources(
        query: str | None = None,
        validation_status: str | None = None,
        screening_status: str | None = None,
        evidence_role: str | None = None,
        target_construct: str | None = None,
        risk_flag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search canonical sources using text and existing controlled filters."""
        return service.search_sources(
            query=query,
            validation_status=validation_status,
            screening_status=screening_status,
            evidence_role=evidence_role,
            target_construct=target_construct,
            risk_flag=risk_flag,
            limit=limit,
            offset=offset,
        )

    @server.tool(annotations=READ_ONLY)
    def get_source_context(source_id: str) -> dict[str, Any]:
        """Get a source with alias resolution, clusters, relations, and evidence rows."""
        return service.get_source_context(source_id)

    @server.tool(annotations=READ_ONLY)
    def search_resources(
        query: str | None = None,
        validation_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search tools, datasets, repositories, and other resources in ST.json."""
        return service.search_resources(query, validation_status, limit, offset)

    @server.tool(annotations=READ_ONLY)
    def get_cluster(cluster_id: str, expand_sources: bool = False) -> dict[str, Any]:
        """Get an active or retired cluster, optionally expanding member source cards."""
        return service.get_cluster(cluster_id, expand_sources)

    @server.tool(annotations=READ_ONLY)
    def search_evidence(
        query: str | None = None,
        source_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search traceable claims, evidence, limitations, and permitted conclusions."""
        return service.search_evidence(query, source_id, limit, offset)

    @server.tool(annotations=READ_ONLY)
    def search_novelty(
        query: str | None = None,
        prior_art_outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search unranked Drosophila x ECAP x SCS novelty variants."""
        return service.search_novelty(query, prior_art_outcome, limit, offset)

    @server.tool(annotations=READ_ONLY)
    def get_dissertation_concept() -> dict[str, Any]:
        """Return the umbrella topic, goal, hypothesis, tasks, and traceable claims."""
        return service.get_dissertation_concept()

    @server.tool(annotations=WRITE)
    def save_candidate(filename: str, candidate: dict[str, Any] | list[Any]) -> dict[str, Any]:
        """Validate and atomically save a new, non-overwriting inbox candidate."""
        return service.save_candidate(filename, candidate)

    @server.tool(annotations=WRITE)
    def publish_candidate(filename: str, apply: bool = False) -> dict[str, Any]:
        """Validate an inbox candidate; publish only when apply is explicitly true."""
        return service.publish_candidate(filename, apply=apply)

    @server.tool(annotations=WRITE)
    def review_batch(batch: str, apply: bool = False) -> dict[str, Any]:
        """Check a curation review batch; apply atomically only with apply=true."""
        return service.review_batch(batch, apply=apply)

    @server.tool(annotations=WRITE)
    def cluster_manifest(manifest: str, apply: bool = False) -> dict[str, Any]:
        """Check a cluster manifest; apply atomically only with apply=true."""
        return service.cluster_manifest(manifest, apply=apply)

    @server.tool(annotations=WRITE)
    def snapshot(label: str) -> dict[str, Any]:
        """Create a named immutable snapshot of the canonical research artifacts."""
        return service.snapshot(label)

    @server.resource("research://knowledge-guide", mime_type="text/markdown")
    def knowledge_guide() -> str:
        return service.read_text("knowledge/README.md")

    @server.resource("research://knowledge-registry", mime_type="application/json")
    def knowledge_registry() -> str:
        return service.read_text("knowledge/corpus-manifest.json")

    @server.resource("research://guide", mime_type="text/markdown")
    def guide() -> str:
        return service.read_text("README.md")

    @server.resource("research://todo", mime_type="text/markdown")
    def todo() -> str:
        return service.read_text("TODO.md")

    @server.resource("research://todo-decisions", mime_type="text/markdown")
    def todo_decisions() -> str:
        return service.read_text("docs/audits/todo-decision-ledger.md")

    @server.resource("research://operations", mime_type="text/markdown")
    def operations() -> str:
        return service.read_text("docs/reference/operations.md")

    @server.resource("research://docs-index", mime_type="text/markdown")
    def docs_index() -> str:
        return service.read_text("docs/README.md")

    @server.resource("research://research-status", mime_type="text/markdown")
    def research_status() -> str:
        return service.read_text("docs/final-validation-report.md")

    @server.resource("research://evidence-audit", mime_type="text/markdown")
    def evidence_audit() -> str:
        return service.read_text("docs/audits/evd03-evidence-matrix-audit-2026-09-25.md")

    @server.resource("research://audit", mime_type="application/json")
    def audit() -> str:
        return service.read_text("data/audits/summary/audit-report.json")

    @server.resource("research://evidence-matrix", mime_type="application/json")
    def evidence_matrix() -> str:
        return service.read_text("data/evidence/evidence-matrix.json")

    @server.resource("research://scientific-contract", mime_type="text/markdown")
    def scientific_contract() -> str:
        return service.read_text("docs/scientific-contract.md")

    @server.resource("research://human-dataset-matrix", mime_type="application/json")
    def human_dataset_matrix() -> str:
        return service.read_text("data/evidence/human-dataset-matrix.json")

    @server.resource("research://completeness", mime_type="application/json")
    def completeness() -> str:
        return service.read_text("data/audits/summary/completeness-report.json")

    @server.resource("research://search-protocol", mime_type="application/json")
    def search_protocol() -> str:
        return service.read_text("data/audits/search/search-protocol.json")

    @server.resource("research://novelty-landscape", mime_type="application/json")
    def novelty_landscape() -> str:
        return service.read_text("data/research/novelty-landscape.json")

    @server.resource("research://dissertation-concept", mime_type="application/json")
    def dissertation_concept() -> str:
        return service.read_text("data/research/dissertation-concept.json")

    @server.resource("research://runtime-audit", mime_type="application/json")
    def runtime_audit() -> str:
        return service.read_text("data/audits/drosophila/runtime-audit.json")

    @server.resource("research://schema/source-record", mime_type="application/schema+json")
    def source_schema() -> str:
        return service.read_text("data/schema/source-record.schema.json")

    @server.resource("research://vocabularies", mime_type="application/json")
    def vocabularies() -> str:
        return service.read_text("data/schema/vocabularies.json")

    @server.resource("research://source/{source_id}", mime_type="application/json")
    def source(source_id: str) -> str:
        return service.source_resource(source_id)

    @server.resource("research://cluster/{cluster_id}", mime_type="application/json")
    def cluster(cluster_id: str) -> str:
        return service.cluster_resource(cluster_id)

    return server


mcp = create_server()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
