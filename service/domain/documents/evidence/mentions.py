"""Resolve explicit locators in supplied material against the owned source registry."""

from __future__ import annotations

import re
from collections.abc import Iterable

from service.domain.subagents.research.sources import SourceRecord, normalize_url

_URL = re.compile(r"https?://[^\s<>{}\[\]|\\\^`\"]+", re.IGNORECASE)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


def referenced_citations(text: str, records: Iterable[SourceRecord]) -> frozenset[int]:
    """No fetching, inferred author/year, substring matching or new source admission."""
    urls = {
        canonical
        for match in _URL.finditer(text)
        if (canonical := normalize_url(match.group(0).rstrip(".,;:)"))) is not None
    }
    dois = {match.group(0).rstrip(".,;)").casefold() for match in _DOI.finditer(text)}
    return frozenset(
        record.source_id
        for record in records
        if record.canonical_url in urls or (record.doi and record.doi.casefold() in dois)
    )
