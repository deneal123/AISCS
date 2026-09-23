"""Bounded local stdio MCP for a document sidecar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .core import DocumentSidecar, SidecarError

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def create_server(root: Path | str | None = None) -> MCPServer:
    sidecar = DocumentSidecar(root or Path(__file__).resolve().parents[1])
    server = MCPServer(
        sidecar.config["mcp_name"],
        version=sidecar.config["version"],
        instructions=(
            "This server manages bounded dissertation document sources. Draft placeholders are "
            "not scientific results. Research evidence is usable only through an imported "
            "immutable "
            "snapshot. Mutations require apply=true and immutable submissions cannot be edited."
            " A simulation label is not subjective pain, ECAP is not a direct pain measure, "
            "and source verification is not independent reproduction."
        ),
        log_level="WARNING",
    )

    @server.tool(annotations=READ)
    def status() -> dict[str, Any]:
        return sidecar.status()

    @server.tool(annotations=READ)
    def list_documents() -> dict[str, Any]:
        return sidecar.list_documents()

    @server.tool(annotations=READ)
    def get_document_context(document_id: str) -> dict[str, Any]:
        document = sidecar.get_document(document_id)
        if document is None:
            raise SidecarError("document not found")
        return {"document": document, "research_snapshot": sidecar.get_research_snapshot()}

    @server.tool(annotations=READ)
    def validate(profile: str = "draft") -> dict[str, Any]:
        return sidecar.validate(profile=profile)

    @server.tool(annotations=READ)
    def get_research_snapshot() -> dict[str, Any]:
        return sidecar.get_research_snapshot()

    @server.tool(annotations=WRITE)
    def save_section(
        path: str,
        content: str,
        expected_sha256: str | None = None,
        apply: bool = False,
    ) -> dict[str, Any]:
        return sidecar.save_section(path, content, expected_sha256, apply=apply)

    @server.tool(annotations=WRITE)
    def build(document_id: str, profile: str = "draft", apply: bool = False) -> dict[str, Any]:
        return sidecar.build(document_id, profile, apply=apply)

    @server.tool(annotations=WRITE)
    def snapshot(label: str, apply: bool = False) -> dict[str, Any]:
        if not apply:
            return {"ok": True, "applied": False, "label": label}
        return {**sidecar.snapshot(label), "applied": True}

    @server.tool(annotations=WRITE)
    def import_research_snapshot(
        research_dir: str, refs: list[str], apply: bool = False
    ) -> dict[str, Any]:
        return sidecar.import_research(research_dir, refs, apply=apply)

    @server.tool(annotations=WRITE)
    def release(document_id: str, version: str, apply: bool = False) -> dict[str, Any]:
        return sidecar.release(document_id, version, apply=apply)

    @server.resource("document://guide", mime_type="text/markdown")
    def guide() -> str:
        return (sidecar.root / "README.md").read_text(encoding="utf-8")

    @server.resource("document://todo", mime_type="text/markdown")
    def todo() -> str:
        return (sidecar.root / "TODO.md").read_text(encoding="utf-8")

    @server.resource("document://registry", mime_type="application/json")
    def registry() -> str:
        return json.dumps(sidecar.registry, ensure_ascii=False, indent=2)

    @server.resource("document://outline", mime_type="text/markdown")
    def outline() -> str:
        path = sidecar.root / sidecar.config["outline"]
        return path.read_text(encoding="utf-8")

    @server.resource("document://research-snapshot", mime_type="application/json")
    def research_snapshot() -> str:
        path = sidecar.root / "data" / "research-snapshot" / "snapshot.json"
        return path.read_text(encoding="utf-8") if path.is_file() else "{}"

    @server.resource("document://document/{document_id}", mime_type="application/json")
    def document(document_id: str) -> str:
        item = sidecar.get_document(document_id)
        if item is None:
            raise SidecarError("document not found")
        return json.dumps(item, ensure_ascii=False, indent=2)

    @server.resource("document://validation-report/{document_id}", mime_type="application/json")
    def validation_report(document_id: str) -> str:
        path = sidecar.root / "build" / document_id.lower() / "validation-report.json"
        return path.read_text(encoding="utf-8") if path.is_file() else "{}"

    return server


mcp = create_server()


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
