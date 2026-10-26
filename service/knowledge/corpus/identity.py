"""Identifier extraction and identity validation against the canonical registry."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...common.errors import CorpusError
from .text import WHITESPACE_RE

DOI_RE = re.compile(r"\b10\.[0-9]{4,9}/[^\s\"'<>()\[\]{}]+", re.IGNORECASE)
_PMID_RE = re.compile(r"\bPMID[:\s]*([0-9]{6,9})\b", re.IGNORECASE)
_PMCID_RE = re.compile(r"\b(PMC[0-9]{6,9})\b", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\barXiv[:\s]*([0-9]{4}\.[0-9]{4,5})(v[0-9]+)?", re.IGNORECASE)
_NCT_RE = re.compile(r"\b(NCT[0-9]{8})\b", re.IGNORECASE)
_GEO_RE = re.compile(r"\b(GSE[0-9]{3,})\b", re.IGNORECASE)
_SYN_RE = re.compile(r"\b(syn[0-9]{6,})\b", re.IGNORECASE)
_PRJ_RE = re.compile(r"\b(PRJ[END][A-Z][0-9]{4,})\b", re.IGNORECASE)

TITLE_STOPWORDS = frozenset(
    {
        "abstract",
        "summary",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
        "acknowledgements",
        "acknowledgments",
        "article",
        "research article",
        "original article",
        "review",
        "preprint",
        "doi",
        "journal",
        "volume",
        "downloaded from",
        "accepted manuscript",
        "supplementary material",
    }
)


# ---------------------------------------------------------------------------
# identifiers and identity validation
# ---------------------------------------------------------------------------


def normalize_title(value: str | None) -> str | None:
    if not value:
        return None
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^0-9a-z\u0400-\u04ff]+", " ", folded)
    folded = WHITESPACE_RE.sub(" ", folded).strip()
    return folded or None


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip(".,;)]}").casefold()
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned)
    return cleaned or None


def extract_identifiers(text: str) -> dict[str, Any]:
    """Extract DOI/accession candidates from document text (never from filenames)."""
    head = text[:200000]
    dois = sorted({match.group(0).rstrip(".,;)]}").casefold() for match in DOI_RE.finditer(head)})
    pmids = sorted({match.group(1) for match in _PMID_RE.finditer(head)})
    pmcids = sorted({match.group(1).upper() for match in _PMCID_RE.finditer(head)})
    arxiv = sorted(
        {f"{match.group(1)}{match.group(2) or ''}" for match in _ARXIV_RE.finditer(head)}
    )
    nct = sorted({match.group(1).upper() for match in _NCT_RE.finditer(head)})
    geo = sorted({match.group(1).upper() for match in _GEO_RE.finditer(head)})
    synapse = sorted({match.group(1) for match in _SYN_RE.finditer(head)})
    bioproject = sorted({match.group(1).upper() for match in _PRJ_RE.finditer(head)})
    return {
        "doi": dois,
        "pmid": pmids,
        "pmcid": pmcids,
        "arxiv_id": arxiv,
        "nct": nct,
        "geo": geo,
        "synapse": synapse,
        "bioproject": bioproject,
    }


def validate_identity(
    extracted: Mapping[str, Any],
    expected: Mapping[str, Any] | None,
    *,
    title: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Validate document title/DOI/accession against a canonical identity.

    ``extracted`` is the output of :func:`extract_identifiers`; ``expected`` maps
    canonical fields (``title``, ``doi``, ``pmid``, ``arxiv_id``, ``dataset_id``,
    ``patent_id``, ``exact_url``). A filename is never consulted.
    """
    evidence: dict[str, Any] = {"matched": [], "checked": [], "title": title}
    if not expected:
        evidence["reason"] = "no_canonical_identity"
        return False, evidence

    norm_doc_title = normalize_title(title)
    norm_expected_title = normalize_title(expected.get("title"))
    if norm_doc_title and norm_expected_title:
        evidence["checked"].append("title")
        if norm_doc_title == norm_expected_title:
            evidence["matched"].append("title")
    expected_doi = _normalize_doi(expected.get("doi"))
    doc_dois = {_normalize_doi(item) for item in extracted.get("doi", [])}
    doc_dois.discard(None)
    if expected_doi:
        evidence["checked"].append("doi")
        if expected_doi in doc_dois:
            evidence["matched"].append("doi")

    accession_pairs = (
        ("pmid", extracted.get("pmid", [])),
        ("pmcid", extracted.get("pmcid", [])),
        ("arxiv_id", extracted.get("arxiv_id", [])),
        ("nct", extracted.get("nct", [])),
        ("geo", extracted.get("geo", [])),
        ("synapse", extracted.get("synapse", [])),
        ("bioproject", extracted.get("bioproject", [])),
    )
    doc_accessions = {str(item).upper() for _kind, items in accession_pairs for item in items}
    for field in ("pmid", "arxiv_id", "dataset_id", "patent_id"):
        canonical_value = expected.get(field)
        if not canonical_value:
            continue
        evidence["checked"].append(field)
        normalized = str(canonical_value).upper()
        if normalized in doc_accessions or any(
            normalized in str(item).upper() for item in doc_accessions
        ):
            evidence["matched"].append(field)

    evidence["extracted"] = {
        "doi": sorted(doc_dois),
        "accessions": sorted(doc_accessions),
    }
    matched = bool(evidence["matched"])
    if not evidence["checked"]:
        evidence["reason"] = "canonical_identity_has_no_comparable_fields"
        return False, evidence
    if not matched:
        evidence["reason"] = "identity_not_matched"
    return matched, evidence


# ---------------------------------------------------------------------------
# canonical registry (read-only)
# ---------------------------------------------------------------------------


def _records_path(root: Path) -> Path | None:
    for candidate in (root / "data" / "records.json", root / "records.json"):
        if candidate.is_file():
            return candidate
    return None


def _identity_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    sources = payload.get("sources") if isinstance(payload, Mapping) else None
    if not isinstance(sources, list):
        return {}
    identities: dict[str, dict[str, Any]] = {}
    for record in sources:
        if not isinstance(record, Mapping):
            continue
        source_id = record.get("id")
        if not isinstance(source_id, str) or not re.fullmatch(r"S[0-9]{3,}", source_id):
            continue
        identifiers = record.get("identifiers") or {}
        if not isinstance(identifiers, Mapping):
            identifiers = {}
        identities[source_id] = {
            "title": record.get("название") or record.get("title"),
            "doi": identifiers.get("doi"),
            "pmid": identifiers.get("pmid"),
            "arxiv_id": identifiers.get("arxiv_id"),
            "patent_id": identifiers.get("patent_id"),
            "dataset_id": identifiers.get("dataset_id"),
            "exact_url": identifiers.get("exact_url"),
        }
    return identities


def _mapping_with_sources(repository: Any) -> Mapping[str, Any] | None:
    if isinstance(repository, Mapping) and "sources" in repository:
        return repository
    return None


def repository_view(repository: Any) -> tuple[Path | None, dict[str, dict[str, Any]]]:
    """Accept a project root, a data directory, a registry mapping or a repository object.

    Returns ``(project_root, identities)``. ``project_root`` is ``None`` only when
    the caller supplied a bare registry mapping without any filesystem anchor.
    """
    mapping = _mapping_with_sources(repository)
    if mapping is not None:
        return None, _identity_from_payload(mapping)
    if hasattr(repository, "bundle") and callable(repository.bundle):
        records: Mapping[str, Any] = {}
        try:
            bundle = repository.bundle()
            records = getattr(bundle, "records", None) or {}
        except Exception:  # noqa: BLE001 - repository boundary; treat as unavailable
            records = {}
        data_dir = getattr(repository, "data_dir", None)
        root = Path(data_dir).resolve().parent if data_dir else None
        return root, _identity_from_payload(records)
    sources_attr = getattr(repository, "sources", None)
    if sources_attr is not None and not isinstance(repository, (str, Path)):
        return None, _identity_from_payload({"sources": list(sources_attr)})

    path = Path(repository)
    if path.is_file():
        parent = path.parent
        root = parent.parent if parent.name == "data" else parent
        records_path: Path | None = path
    elif path.is_dir():
        records_path = _records_path(path)
        if records_path is None:
            return path, {}
        root = (
            path
            if records_path == path / "data" / "records.json"
            else (path.parent if path.name == "data" else path)
        )
    else:
        raise CorpusError(f"repository does not exist: {path}")
    if records_path is None:
        return root, {}
    try:
        payload = json.loads(records_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return root, {}
    return root, _identity_from_payload(payload)


def load_canonical_identity(repository: Any) -> dict[str, dict[str, Any]]:
    """Read the canonical registry read-only and return ``source_id -> identity``.

    ``repository`` may be the project root (``data/records.json`` is preferred,
    with a bare ``records.json`` fallback), the ``data`` directory itself, a
    ``ResearchRepository``-like object exposing ``bundle()``/``data_dir``, or a
    mapping carrying ``sources``. A missing or malformed registry yields ``{}``
    and the caller must then treat every candidate as identity-unverified.
    """
    return repository_view(repository)[1]
