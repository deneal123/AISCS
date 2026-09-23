"""Private, deterministic evidence assembled for one document-authoring run.

The browser-facing attachment metadata is deliberately not reused as an evidence
contract.  This module accepts the already owner-checked run attachments and research
artifact, assigns stable opaque source identifiers, and exposes two separate views:

* bounded material chunks which an authoring model may read;
* bibliographic records which were actually present in the material or research.

Neither view is suitable for trace/log metadata.  Callers may only project ``summary``.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from service.domain.subagents.research import ResearchArtifact, SourceRegistry

MAX_ATTACHMENTS = 8
MAX_ATTACHMENT_CHARS = 120_000
MAX_BUNDLE_CHARS = 240_000
CHUNK_CHARS = 4_000
MAX_CHUNKS = 64

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]{2,240})\]\((https?://[^\s)]+)\)", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s<>{}\[\]|\\\^`\"]+", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|2100)\b")


def _clean(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", " ").strip()[:limit]


def _safe_name(value: Any) -> str:
    raw = _clean(value, 260).replace("\\", "/").rsplit("/", 1)[-1]
    return raw or "material"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _chunks(text: str) -> Iterable[str]:
    """Split on paragraph boundaries while preserving all bounded source text."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cursor = 0
    while cursor < len(normalized):
        end = min(len(normalized), cursor + CHUNK_CHARS)
        if end < len(normalized):
            split = normalized.rfind("\n\n", cursor + CHUNK_CHARS // 2, end)
            if split > cursor:
                end = split
        chunk = normalized[cursor:end].strip()
        if chunk:
            yield chunk
        cursor = end
        while cursor < len(normalized) and normalized[cursor].isspace():
            cursor += 1


@dataclass(frozen=True, slots=True)
class DocumentEvidenceChunk:
    source_id: str
    attachment_id: str
    ordinal: int
    text: str

    def prompt_block(self) -> str:
        return f"Материал {self.source_id}\n{self.text}"


@dataclass(frozen=True, slots=True)
class DocumentEvidenceAttachment:
    source_id: str
    file_id: str | None
    safe_name: str
    mime_type: str
    sha256: str
    chunks: tuple[DocumentEvidenceChunk, ...]


@dataclass(frozen=True, slots=True)
class DocumentEvidenceBundle:
    """Run-scoped source bundle. Contents must never be projected to public metadata."""

    schema_version: int
    attachments: tuple[DocumentEvidenceAttachment, ...]
    research: ResearchArtifact | None
    bibliography: ResearchArtifact
    digest: str

    @property
    def material_source_ids(self) -> frozenset[str]:
        return frozenset(chunk.source_id for item in self.attachments for chunk in item.chunks)

    @property
    def has_materials(self) -> bool:
        return bool(self.attachments or (self.research and self.research.records))

    @property
    def has_bibliography(self) -> bool:
        return bool(self.bibliography.records)

    def prompt_context(self, *, max_chars: int = 60_000) -> str:
        blocks: list[str] = []
        used = 0
        for attachment in self.attachments:
            for chunk in attachment.chunks:
                block = chunk.prompt_block()
                if used + len(block) > max_chars:
                    remaining = max_chars - used
                    if remaining >= 256:
                        blocks.append(block[:remaining])
                    return "\n\n".join(blocks)
                blocks.append(block)
                used += len(block)
        if self.research is not None:
            for record in self.research.records:
                block = record.synthesis_block(max_chars=2_400)
                if used + len(block) > max_chars:
                    break
                blocks.append(block)
                used += len(block)
        return "\n\n".join(blocks)

    def summary(self) -> dict[str, int | bool]:
        """Only safe aggregate facts suitable for document status events."""

        return {
            "attachment_count": len(self.attachments),
            "material_chunk_count": sum(len(item.chunks) for item in self.attachments),
            "research_source_count": len(self.research.records) if self.research else 0,
            "bibliography_source_count": len(self.bibliography.records),
            "bibliography_complete": self.has_bibliography,
        }


def _attachment_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        mapped = dump()
        return mapped if isinstance(mapped, dict) else {}
    return {
        "file_id": getattr(value, "file_id", None),
        "name": getattr(value, "name", None),
        "mime_type": getattr(value, "mime_type", None),
        "digest": getattr(value, "digest", None),
        "content": getattr(value, "content", None),
    }


def _bibliography_candidates(text: str) -> Iterable[dict[str, Any]]:
    seen: set[str] = set()
    for title, url in _MARKDOWN_LINK_RE.findall(text):
        cleaned_url = url.rstrip(".,;:)")
        if cleaned_url in seen:
            continue
        seen.add(cleaned_url)
        line = next((part for part in text.splitlines() if cleaned_url in part), title)
        doi_match = _DOI_RE.search(line)
        year_match = _YEAR_RE.search(line)
        yield {
            "url": cleaned_url,
            "title": _clean(title, 240),
            "content": _clean(line, 4_000),
            "year": int(year_match.group(1)) if year_match else None,
            "doi": doi_match.group(0).rstrip(".,;)") if doi_match else None,
        }
    for doi_match in _DOI_RE.finditer(text):
        doi = doi_match.group(0).rstrip(".,;)")
        url = f"https://doi.org/{doi}"
        if url in seen:
            continue
        seen.add(url)
        line_start = text.rfind("\n", 0, doi_match.start()) + 1
        line_end = text.find("\n", doi_match.end())
        line = text[line_start : line_end if line_end >= 0 else len(text)].strip()
        year_match = _YEAR_RE.search(line)
        yield {
            "url": url,
            "title": _clean(line, 240) or f"DOI {doi}",
            "content": _clean(line, 4_000),
            "year": int(year_match.group(1)) if year_match else None,
            "doi": doi,
        }
    for url_match in _URL_RE.finditer(text):
        url = url_match.group(0).rstrip(".,;:)")
        if url in seen:
            continue
        seen.add(url)
        line_start = text.rfind("\n", 0, url_match.start()) + 1
        line_end = text.find("\n", url_match.end())
        line = text[line_start : line_end if line_end >= 0 else len(text)].strip()
        if len(line) < 12:
            continue
        year_match = _YEAR_RE.search(line)
        yield {
            "url": url,
            "title": _clean(line.replace(url, " "), 240) or "Предоставленный источник",
            "content": _clean(line, 4_000),
            "year": int(year_match.group(1)) if year_match else None,
            "doi": None,
        }


def build_document_evidence_bundle(
    attachments: Iterable[Any] | None,
    research: ResearchArtifact | None,
) -> DocumentEvidenceBundle:
    normalized: list[DocumentEvidenceAttachment] = []
    bibliography = SourceRegistry(max_sources=64)
    total_chars = 0
    total_chunks = 0

    for value in list(attachments or ())[:MAX_ATTACHMENTS]:
        raw = _attachment_mapping(value)
        content = _clean(raw.get("content"), MAX_ATTACHMENT_CHARS)
        if not content or total_chars >= MAX_BUNDLE_CHARS or total_chunks >= MAX_CHUNKS:
            continue
        content = content[: MAX_BUNDLE_CHARS - total_chars]
        supplied_digest = str(raw.get("digest") or raw.get("sha256") or "").lower()
        content_digest = (
            supplied_digest if re.fullmatch(r"[0-9a-f]{64}", supplied_digest) else _digest(content)
        )
        attachment_id = f"att-{content_digest[:16]}"
        item_chunks: list[DocumentEvidenceChunk] = []
        for ordinal, chunk in enumerate(_chunks(content), start=1):
            if total_chunks >= MAX_CHUNKS:
                break
            item_chunks.append(
                DocumentEvidenceChunk(
                    source_id=f"{attachment_id}-c{ordinal:03d}",
                    attachment_id=attachment_id,
                    ordinal=ordinal,
                    text=chunk,
                )
            )
            total_chunks += 1
        if not item_chunks:
            continue
        total_chars += sum(len(chunk.text) for chunk in item_chunks)
        normalized.append(
            DocumentEvidenceAttachment(
                source_id=attachment_id,
                file_id=_clean(raw.get("file_id"), 80) or None,
                safe_name=_safe_name(raw.get("name") or raw.get("filename")),
                mime_type=_clean(raw.get("mime_type") or raw.get("content_type"), 120)
                or "text/plain",
                sha256=content_digest,
                chunks=tuple(item_chunks),
            )
        )
        for candidate in _bibliography_candidates(content):
            bibliography.add(content_kind="page", **candidate)

    if research is not None:
        for record in research.records:
            bibliography.add(
                url=record.canonical_url,
                title=record.title,
                content=record.content,
                content_kind=record.content_kind,
                authors=list(record.authors),
                year=record.year,
                doi=record.doi,
            )

    digest_payload = "\n".join(
        [*(item.sha256 for item in normalized), research.digest if research else ""]
    )
    return DocumentEvidenceBundle(
        schema_version=1,
        attachments=tuple(normalized),
        research=research,
        bibliography=bibliography.artifact(status="ready" if bibliography.records else "empty"),
        digest=_digest(digest_payload),
    )


__all__ = [
    "DocumentEvidenceAttachment",
    "DocumentEvidenceBundle",
    "DocumentEvidenceChunk",
    "build_document_evidence_bundle",
]
