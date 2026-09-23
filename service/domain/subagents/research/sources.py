"""Safe source normalization and a registry that owns every allowed citation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = frozenset({"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"})
_SPACE_RE = re.compile(r"\s+")


def normalize_url(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw or len(raw) > 4096:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname.lower().rstrip(".")
    if not host:
        return None
    netloc = host
    default_port = (parts.scheme == "http" and port == 80) or (
        parts.scheme == "https" and port == 443
    )
    if port and not default_port:
        netloc = f"{host}:{port}"
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_KEYS and not key.lower().startswith(_TRACKING_PREFIXES)
        )
    )
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    return _SPACE_RE.sub(" ", text)[:limit].strip()


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: int
    canonical_url: str
    title: str
    content: str
    content_kind: str
    fingerprint: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    doi: str | None = None

    @property
    def citation(self) -> str:
        return f"[{self.source_id}]"

    def synthesis_block(self, *, max_chars: int = 2400) -> str:
        # URLs deliberately stay out of model prompts. The numeric registry is enough
        # to produce citations and prevents a model from inventing links.
        return (
            f"Источник [{self.source_id}]\n"
            f"Название: {self.title}\n"
            f"Материал: {self.content[:max_chars]}"
        )


class SourceRegistry:
    """Deduplicate by canonical URL and content while preserving insertion order."""

    def __init__(self, *, max_sources: int = 12) -> None:
        self.max_sources = max(1, int(max_sources))
        self._records: list[SourceRecord] = []
        self._by_url: dict[str, SourceRecord] = {}
        self._fingerprints: set[str] = set()

    def add(
        self,
        *,
        url: Any,
        title: Any,
        content: Any,
        content_kind: str,
        authors: Any = None,
        year: Any = None,
        doi: Any = None,
    ) -> SourceRecord | None:
        canonical = normalize_url(url)
        body = _clean_text(content, 12000)
        if canonical is None or len(body) < 12:
            return None
        if canonical in self._by_url:
            return self._by_url[canonical]
        fingerprint = hashlib.sha256(body.casefold().encode("utf-8")).hexdigest()
        if fingerprint in self._fingerprints or len(self._records) >= self.max_sources:
            return None
        safe_title = _clean_text(title, 240) or f"Источник {len(self._records) + 1}"
        safe_authors = (
            tuple(item for item in (_clean_text(value, 160) for value in (authors or [])) if item)[
                :16
            ]
            if isinstance(authors, list)
            else ()
        )
        try:
            safe_year = int(year) if year is not None else None
        except (TypeError, ValueError):
            safe_year = None
        if safe_year is not None and not 1000 <= safe_year <= 3000:
            safe_year = None
        safe_doi = _clean_text(doi, 240) or None
        record = SourceRecord(
            source_id=len(self._records) + 1,
            canonical_url=canonical,
            title=safe_title,
            content=body,
            content_kind=content_kind if content_kind in {"page", "snippet"} else "snippet",
            fingerprint=fingerprint,
            authors=safe_authors,
            year=safe_year,
            doi=safe_doi,
        )
        self._records.append(record)
        self._by_url[canonical] = record
        self._fingerprints.add(fingerprint)
        return record

    @property
    def records(self) -> tuple[SourceRecord, ...]:
        return tuple(self._records)

    @property
    def ids(self) -> frozenset[int]:
        return frozenset(record.source_id for record in self._records)

    def synthesis_context(self, *, max_total_chars: int = 18000) -> str:
        blocks: list[str] = []
        total = 0
        for record in self._records:
            block = record.synthesis_block()
            if total + len(block) > max_total_chars:
                remaining = max_total_chars - total
                if remaining > 200:
                    blocks.append(block[:remaining])
                break
            blocks.append(block)
            total += len(block)
        return "\n\n".join(blocks)

    def sources_section(self) -> str:
        if not self._records:
            return "### Источники"
        lines = ["### Источники"]
        for record in self._records:
            lines.append(f"{record.source_id}. [{record.title}]({record.canonical_url})")
        return "\n".join(lines)

    def bounded_metadata(self) -> dict[str, int]:
        return {
            "source_count": len(self._records),
            "page_count": sum(1 for item in self._records if item.content_kind == "page"),
            "snippet_count": sum(1 for item in self._records if item.content_kind == "snippet"),
        }

    def artifact(self, *, status: str = "ready") -> ResearchArtifact:
        return ResearchArtifact(schema_version=1, records=self.records, status=status)


@dataclass(frozen=True, slots=True)
class ResearchArtifact:
    """Private evidence handoff shared by native research, LDR, and authoring."""

    schema_version: int
    records: tuple[SourceRecord, ...]
    status: str = "ready"

    @property
    def digest(self) -> str:
        payload = "\n".join(
            f"{item.source_id}:{item.fingerprint}:{item.canonical_url}" for item in self.records
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def source_ids(self) -> frozenset[int]:
        return frozenset(item.source_id for item in self.records)


def artifact_from_external_sources(sources: list[Any]) -> ResearchArtifact:
    registry = SourceRegistry(max_sources=32)
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        registry.add(
            url=source.get("url") or source.get("link") or source.get("href"),
            title=source.get("title") or source.get("name"),
            content=(source.get("content") or source.get("snippet") or source.get("description")),
            content_kind="snippet",
            authors=source.get("authors"),
            year=source.get("year"),
            doi=source.get("doi"),
        )
    return registry.artifact(status="ready" if registry.records else "empty")


__all__ = [
    "ResearchArtifact",
    "SourceRecord",
    "SourceRegistry",
    "artifact_from_external_sources",
    "normalize_url",
]
