"""Deterministic semantic edits; no model, compiler or untrusted preamble changes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

from service.domain.documents.evidence.registered_sources import registered_sources
from service.domain.documents.intent import parse_document_intent
from service.domain.documents.publisher_language import publisher_language
from service.domain.documents.semantic.draft import DocumentDraft, DraftBlock, parse_document_draft
from service.domain.documents.semantic.rendering import render_document


class ExistingCitations:
    def __init__(self, bibliography: str) -> None:
        self.keys = {
            item["source_id"]: item["key"] for item in registered_sources(bibliography)["sources"]
        }

    def key_for(self, source_id: int) -> str | None:
        return self.keys.get(source_id)


def render_edit(files: dict[str, str], proposed: dict, version: int, digest: str) -> dict:
    """Reject stale drafts and unmanaged TeX edits rather than overwriting them."""
    if len(files) > 128 or sum(len(text.encode()) for text in files.values()) > 2_000_000:
        raise ValueError("authoring_invalid")
    manifest = json.loads(files.get(".gpthub-authoring.json", "{}"))
    old = parse_document_draft(manifest.get("draft"))
    new = parse_document_draft(proposed)
    intent = parse_document_intent(manifest.get("intent", {}), "")
    if old is None or new is None or intent is None:
        raise ValueError("authoring_invalid")
    if len(old.blocks) == 1 and old.blocks[0].block_id == "literal_text":
        intent = replace(intent, literal_text=old.blocks[0].text)
    if old.version != version or old.digest != digest or new.version != version:
        raise ValueError("source_changed")
    # Editing cannot change the stable identity of existing blocks. New semantic
    # blocks must be assigned by a separate trusted operation, not browser input.
    existing = {block.block_id: block for block in old.blocks}
    assigned = []
    for index, block in enumerate(new.blocks):
        if block.block_id in existing:
            if block.kind != existing[block.block_id].kind:
                raise ValueError("authoring_invalid")
        elif block.block_id.startswith("new_"):
            seed = f"{digest}:{version}:{index}:{block.kind}".encode()
            block = replace(block, block_id="block_" + hashlib.sha256(seed).hexdigest()[:16])
        else:
            raise ValueError("authoring_invalid")
        assigned.append(block)
    new = replace(new, blocks=tuple(assigned))
    bibliography = files.get("bibliography/references.bib", "")
    citations = ExistingCitations(bibliography)
    scaffold = files.get("main.tex", "")
    before = render_document(
        intent,
        old,
        scaffold_source=scaffold,
        citations=citations,
        bibliography=bibliography,
        enforce_evidence=False,
    )
    for path, content in before.files.items():
        if path == ".gpthub-authoring.json":
            continue
        existing = files.get(path, "")
        if path == "main.tex":
            # A renderer-owned empty package list adds a blank preamble line.
            # Ignore only empty preamble lines, never body paragraph boundaries.
            def comparable(text: str) -> tuple[str, str]:
                head, separator, body = text.partition(r"\begin{document}")
                return "\n".join(
                    line for line in head.splitlines() if line.strip()
                ), separator + body

            existing = publisher_language(
                existing, profile_id=intent.profile_id, locale=intent.locale
            )
            if comparable(content) == comparable(existing):
                continue
        if content != existing:
            raise ValueError("source_changed")
    if any(citations.key_for(source) is None for source in new.cited_source_ids):
        raise ValueError("citation_unknown")
    rendered = render_document(
        intent,
        replace(new, version=version + 1),
        scaffold_source=scaffold,
        citations=citations,
        bibliography=bibliography,
        enforce_evidence=False,
    )
    return {
        "files": rendered.files,
        "authoring_version": rendered.authoring_version,
        "draft_digest": rendered.draft_digest,
    }


def render_initial(files: dict[str, str], proposed: dict, project: dict) -> dict:
    """Start an editable document without an authoring model or browser-owned IDs."""
    intent = parse_document_intent(
        {
            "kind": project.get("kind"),
            "profile_id": project.get("profile", {}).get("profile_id"),
            "locale": project.get("locale"),
            "mode": project.get("mode"),
            "title": str(proposed.get("title") or "Новый документ")[:300],
        },
        "",
    )
    if intent is None or len(str(proposed.get("text") or "")) > 20_000:
        raise ValueError("authoring_invalid")
    draft = DocumentDraft(
        1,
        1,
        intent.title,
        (
            DraftBlock(
                "intro",
                "slide" if intent.kind == "presentation" else "paragraph",
                title="Введение" if intent.kind == "presentation" else "",
                text=str(proposed.get("text") or "Начните редактирование документа здесь."),
            ),
        ),
    )
    rendered = render_document(
        intent, draft, scaffold_source=files["main.tex"], enforce_evidence=False
    )
    return {
        "files": rendered.files,
        "authoring_version": rendered.authoring_version,
        "draft_digest": rendered.draft_digest,
    }
