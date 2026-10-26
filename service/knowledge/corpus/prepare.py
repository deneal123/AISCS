"""Corpus preparation: ingest candidates into content-addressed objects and write the
normalized documents, the working manifest and the discovery report.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...common.errors import CorpusError
from ...common.files import atomic_write_bytes, atomic_write_text
from ...common.hashing import sha256_bytes, sha256_text
from ...indexing.fetch import DEFAULT_MAX_BYTES, MAX_HTTP_ATTEMPTS, fetch_url
from .candidates import normalize_candidates, scan_local_sources
from .chunks import chunk_documents
from .identity import extract_identifiers, normalize_title, repository_view, validate_identity
from .parsing import build_sections, parse_document
from .text import assert_within, json_dumps, now_iso

MANIFEST_ENTRY_STATUSES: tuple[str, ...] = (
    "available",
    "missing",
    "unavailable",
    "needs_ocr",
    "rejected",
    "error",
)


# ---------------------------------------------------------------------------
# prepare_corpus
# ---------------------------------------------------------------------------


def prepare_corpus(
    repository: Any,
    state_dir: Path,
    *,
    candidates: list[dict] | None = None,
    download: bool = False,
) -> dict:
    """Build a private corpus store plus an owner-reviewed manifest.

    Parameters
    ----------
    repository:
        Project root (``R:\\Aspa\\research``), its ``data`` directory, a
        ``ResearchRepository``-like object exposing ``bundle()``/``data_dir``, or a
        mapping carrying ``sources`` (that last form has no filesystem anchor and
        is only usable with :func:`load_canonical_identity`). Only ``records.json``
        is ever read, and only to obtain canonical identities.
    state_dir:
        Private state directory. It is forced to resolve inside ``repository``
        (e.g. ``.knowledge``). Objects go to ``state_dir/corpus/objects/<sha256>``
        and normalized documents to ``state_dir/corpus/documents.jsonl``.
    candidates:
        Explicit ``{source_id, path, primary_url, identity_verified}`` mappings.
        ``None`` triggers conservative local discovery, which reports scratch and
        repository artifacts as unresolved and indexes nothing without identity.
    download:
        Opt-in network use for registered primary URLs. Offline by default, at
        most :data:`MAX_HTTP_ATTEMPTS` attempts, no new source searches.

    Returns
    -------
    dict
        Summary with counts, the working manifest, the discovery report and the
        paths of every written artifact. The *tracked* manifest remains owned by
        ROOT and is written separately.
    """
    resolved_root, canonical = repository_view(repository)
    if resolved_root is None:
        raise CorpusError(
            "repository must be a project root, data directory or repository object; "
            "a bare registry mapping provides no filesystem anchor for state_dir"
        )
    repo = resolved_root
    if not repo.is_dir():
        raise CorpusError(f"repository is not a directory: {repo}")
    requested_state = Path(state_dir)
    if not requested_state.is_absolute():
        requested_state = repo / requested_state
    private = requested_state.resolve()
    assert_within(private, repo, what="state_dir")

    corpus_dir = private / "corpus"
    objects_dir = corpus_dir / "objects"
    documents_path = corpus_dir / "documents.jsonl"
    manifest_path = corpus_dir / "manifest.json"
    report_path = corpus_dir / "scratch-discovery.json"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    objects_dir.mkdir(parents=True, exist_ok=True)

    generated_at = now_iso()

    discovery_report: dict[str, Any]
    if candidates is None:
        scanned, truncated = scan_local_sources(repo)
        normalized = [item for item in scanned if item["source_class"] == "candidate"]
        discovery_report = _build_discovery_report(scanned, truncated, generated_at, repo, private)
    else:
        normalized = normalize_candidates(candidates)
        discovery_report = _empty_discovery_report(generated_at, repo, private)

    by_source: dict[str, dict[str, Any]] = {
        item["source_id"]: item for item in normalized if item["source_id"]
    }
    discovery_candidates = [item for item in normalized if not item["source_id"]]

    entries: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    entry_by_source: dict[str, dict[str, Any]] = {}
    previous_documents = {}
    previous_entries = {}
    if documents_path.exists() and manifest_path.exists():
        previous_documents = {
            d["source_id"]: d
            for d in (
                json.loads(line)
                for line in documents_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        }
        previous_entries = {
            e["source_id"]: e
            for e in json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
        }

    ordered_ids = list(canonical.keys())
    if set(by_source) - set(canonical):
        raise CorpusError("candidate references a source outside the canonical registry")

    for source_id in ordered_ids:
        candidate = by_source.get(source_id)
        previous = previous_documents.get(source_id)
        identity_hash = sha256_text(json_dumps(canonical[source_id]))
        old_entry = previous_entries.get(source_id)
        if (
            candidate is None
            and not download
            and old_entry
            and old_entry.get("canonical_identity_sha256") == identity_hash
            and old_entry["status"] != "available"
        ):
            entries.append(old_entry)
            entry_by_source[source_id] = old_entry
            continue
        if previous and previous.get("canonical_identity_sha256") == identity_hash:
            raw = objects_dir / previous["sha256"]
            if (
                raw.exists()
                and sha256_bytes(raw.read_bytes()) == previous["sha256"]
                and sha256_text(previous["text"]) == previous["text_sha256"]
            ):
                entries.append(previous_entries[source_id])
                entry_by_source[source_id] = entries[-1]
                documents.append(previous)
                continue
        entry, document = _resolve_source(
            source_id=source_id,
            candidate=candidate,
            expected=_expected_identity(canonical.get(source_id), candidate),
            repo=repo,
            objects_dir=objects_dir,
            generated_at=generated_at,
            download=download,
        )
        entries.append(entry)
        entry["canonical_identity_sha256"] = identity_hash
        entry_by_source[source_id] = entry
        if document is not None:
            document["canonical_identity_sha256"] = identity_hash
            document["primary_url"] = canonical[source_id].get("exact_url")
            documents.append(document)

    discovery_report["unregistered_candidates"] = [
        _rejected_discovery_entry(candidate, generated_at) for candidate in discovery_candidates
    ]

    for document in documents:
        chunk_count = len(chunk_documents([document]))
        entry_by_source[document["source_id"]]["chunk_count"] = chunk_count

    lines = "".join(json_dumps(document) + "\n" for document in documents)
    atomic_write_text(documents_path, lines)

    manifest = {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "offline": not download,
        "entries": entries,
        "discovery": [item for item in normalized if not item["source_id"]],
    }
    manifest_bytes = (json_dumps(manifest) + "\n").encode("utf-8")
    atomic_write_bytes(manifest_path, manifest_bytes)
    atomic_write_text(report_path, json_dumps(discovery_report) + "\n")

    counts = {status: 0 for status in MANIFEST_ENTRY_STATUSES}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    return {
        "repository": str(repo),
        "state_dir": str(private),
        "generated_at": generated_at,
        "download": download,
        "counts": {
            "canonical_sources": len(canonical),
            "manifest_entries": len(entries),
            "documents": len(documents),
            "scratch_candidates": len(discovery_report.get("scratch_candidates", [])),
            **counts,
        },
        "manifest": manifest,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "manifest_path": str(manifest_path),
        "documents_path": str(documents_path),
        "objects_dir": str(objects_dir),
        "scratch_report_path": str(report_path),
        "unresolved": discovery_report.get("unresolved", []),
    }


def portable_manifest(result: dict, project: Path) -> dict:
    """Public registry contains portable locators; private runtime details stay private."""
    manifest = json.loads(json.dumps(result["manifest"]))
    manifest["repository"] = "."
    manifest["state_dir"] = ".knowledge"
    docs = [
        json.loads(line)
        for line in Path(result["documents_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {doc["source_id"]: doc for doc in docs}
    for entry in manifest["entries"]:
        paths = []
        for raw in entry["paths"]:
            path = Path(raw)
            paths.append(
                path.relative_to(project).as_posix() if path.is_absolute() else path.as_posix()
            )
        entry["paths"] = paths
        entry["completeness"] = by_id.get(entry["source_id"], {}).get("completeness", "unavailable")
    return manifest


def _expected_identity(
    canonical: Mapping[str, Any] | None, candidate: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if canonical:
        return dict(canonical)
    return None


def _new_entry(source_id: str, generated_at: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "status": "missing",
        "reason": "no_candidate_locator",
        "primary_urls": [],
        "paths": [],
        "sha256": None,
        "version": None,
        "bytes": None,
        "retrieved_at": None,
        "checked_at": generated_at,
        "page_count": None,
        "sections": [],
        "chunk_count": 0,
        "identity_verified": False,
        "identity_evidence": {},
        "content_type": None,
        "format": None,
        "http_status": None,
        "error": None,
        "warnings": [],
    }


def _resolve_source(
    *,
    source_id: str,
    candidate: Mapping[str, Any] | None,
    expected: Mapping[str, Any] | None,
    repo: Path,
    objects_dir: Path,
    generated_at: str,
    download: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    entry = _new_entry(source_id, generated_at)
    canonical_url = (expected or {}).get("exact_url")
    if canonical_url:
        entry["primary_urls"] = [str(canonical_url)]
    if candidate is None and not download:
        if canonical_url:
            entry["reason"] = "no_local_copy_registered_primary_url"
        return entry, None

    candidate = candidate or {}

    entry["paths"] = list(candidate.get("paths", []))
    for url in candidate.get("primary_urls", []):
        if download and url != canonical_url:
            raise CorpusError("download URL is not a registered canonical primary route")
        if url not in entry["primary_urls"]:
            entry["primary_urls"].append(url)

    local_error: str | None = None
    for raw_path in entry["paths"]:
        path = Path(raw_path)
        if not path.is_absolute():
            path = repo / path
        if not path.is_file():
            entry["warnings"].append(f"local_path_not_found:{raw_path}")
            local_error = "local_path_not_found"
            continue
        assert_within(path.resolve(), repo, what="candidate path")
        if path.stat().st_size > DEFAULT_MAX_BYTES:
            entry["warnings"].append("local_file_too_large")
            local_error = "local_file_too_large"
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            entry.update(status="error", reason="local_read_failed", error=str(exc))
            return entry, None
        status, document, detail = _ingest_bytes(
            data=data,
            source_id=source_id,
            expected=expected,
            objects_dir=objects_dir,
            generated_at=generated_at,
            origin={"kind": "local", "path": str(path)},
        )
        entry.update(detail)
        if status == "available":
            return entry, document
        if status in {"needs_ocr", "rejected"}:
            return entry, None
        local_error = detail.get("reason") or status

    if entry["primary_urls"] and download:
        for url in entry["primary_urls"]:
            fetch = fetch_url(url, max_attempts=MAX_HTTP_ATTEMPTS)
            entry["http_status"] = fetch.get("status")
            if not fetch.get("ok"):
                entry.update(
                    status="unavailable",
                    reason=fetch.get("error") or "download_failed",
                    error=str(fetch.get("error") or "download_failed"),
                )
                continue
            status, document, detail = _ingest_bytes(
                data=fetch["body"],
                source_id=source_id,
                expected=expected,
                objects_dir=objects_dir,
                generated_at=generated_at,
                origin={
                    "kind": "primary_url",
                    "primary_url": url,
                    "final_url": fetch.get("final_url"),
                },
                content_type=fetch.get("content_type"),
                http_status=fetch.get("status"),
            )
            entry.update(detail)
            if status == "available":
                return entry, document
            return entry, None
        return entry, None

    if entry["primary_urls"]:
        entry.update(status="unavailable", reason="download_disabled")
        return entry, None
    if local_error:
        entry.update(status="missing", reason=local_error)
    return entry, None


def _ingest_bytes(
    *,
    data: bytes,
    source_id: str,
    expected: Mapping[str, Any] | None,
    objects_dir: Path,
    generated_at: str,
    origin: Mapping[str, Any],
    content_type: str | None = None,
    http_status: int | None = None,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    sha256 = sha256_bytes(data)
    version = sha256[:16]
    detail: dict[str, Any] = {
        "sha256": sha256,
        "version": version,
        "bytes": len(data),
        "retrieved_at": generated_at,
        "content_type": content_type,
        "http_status": http_status,
        "error": None,
    }
    origin_path = origin.get("path")
    suffix = Path(str(origin_path)).suffix.lower() if origin_path else None
    parsed = parse_document(
        data,
        url=origin.get("final_url") or origin.get("primary_url"),
        suffix=suffix,
        content_type=content_type,
        http_status=http_status,
    )
    detail["format"] = parsed["format"]
    page_starts = parsed.get("page_starts") or []
    detail["page_count"] = len(page_starts) or None

    if parsed.get("needs_ocr"):
        detail.update(status="needs_ocr", reason=parsed.get("reason") or "no_extractable_text")
        return "needs_ocr", None, detail

    if parsed.get("error_page"):
        detail.update(
            status="rejected",
            reason=parsed.get("error_page") or "error_page_detected",
        )
        return "rejected", None, detail

    text = str(parsed.get("text", ""))
    if any(0xD800 <= ord(character) <= 0xDFFF for character in text):
        detail.update(status="needs_ocr", reason="invalid_pdf_text_encoding")
        return "needs_ocr", None, detail
    # A DOI in the bibliography does not identify the containing article.
    identifiers = extract_identifiers(text[:6000])
    verified, evidence = validate_identity(identifiers, expected, title=parsed.get("title"))
    detail["identity_verified"] = verified
    detail["identity_evidence"] = evidence
    expected_title = normalize_title((expected or {}).get("title"))
    front_matter = normalize_title(text[:6000]) or ""
    if (
        verified
        and not evidence.get("matched") == ["title"]
        and expected_title
        and expected_title not in front_matter
    ):
        verified = False
        detail["identity_verified"] = False
        evidence["reason"] = "identifier_match_requires_front_matter_title"
    if not verified:
        detail.update(status="rejected", reason=evidence.get("reason") or "identity_unverified")
        return "rejected", None, detail

    sections = build_sections(text, parsed.get("headings") or [], page_starts or None)
    detail["sections"] = sections
    atomic_write_bytes(objects_dir / sha256, data)

    document = {
        "parser_version": "normalizer-v1",
        "source_id": source_id,
        "origin": dict(origin),
        "sha256": sha256,
        "version": version,
        "bytes": len(data),
        "format": parsed["format"],
        "content_type": content_type,
        "http_status": http_status,
        "retrieved_at": generated_at,
        "page_count": len(page_starts) or None,
        "page_starts": list(page_starts) or None,
        "sections": sections,
        "title": parsed.get("title"),
        "identity_evidence": evidence,
        "text": text,
        "text_sha256": sha256_text(text),
        "completeness": "full_text"
        if len(text) > 10000
        and any(
            label[1] in {"methods", "results", "discussion"} for label in parsed.get("headings", [])
        )
        else "partial_text",
    }
    detail["status"] = "available"
    detail["reason"] = "parsed_and_identity_verified"
    return "available", document, detail


def _rejected_discovery_entry(candidate: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    source_class = candidate.get("source_class", "candidate")
    entry = _new_entry(str(candidate.get("provisional_id", "local:unknown")), generated_at)
    entry["paths"] = list(candidate.get("paths", []))
    entry.update(
        status="rejected",
        reason="identity_unverified_discovery"
        if source_class == "candidate"
        else f"{source_class}_not_indexed",
        error=None,
    )
    return entry


def _empty_discovery_report(generated_at: str, repo: Path, private: Path) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "counts": {"scratch_candidates": 0, "repository_artifacts": 0, "candidates": 0},
        "scratch_candidates": [],
        "repository_artifacts_sample": [],
        "unresolved": [],
        "note": "explicit candidates supplied; no local discovery was performed",
    }


def _build_discovery_report(
    scanned: Sequence[Mapping[str, Any]],
    truncated: bool,
    generated_at: str,
    repo: Path,
    private: Path,
) -> dict[str, Any]:
    scratch = [item for item in scanned if item["source_class"] == "scratch"]
    artifacts = [item for item in scanned if item["source_class"] == "repository_artifact"]
    candidates = [item for item in scanned if item["source_class"] == "candidate"]
    unresolved = [
        {
            "relative_path": item["relative_path"],
            "reason": "scratch_file_requires_explicit_mapping",
            "bytes": item["bytes"],
        }
        for item in scratch
    ]
    for item in candidates:
        unresolved.append(
            {
                "relative_path": item["relative_path"],
                "reason": "no_canonical_identity_for_discovered_file",
                "bytes": item["bytes"],
            }
        )
    return {
        "generated_at": generated_at,
        "repository": str(repo),
        "state_dir": str(private),
        "truncated": truncated,
        "counts": {
            "scratch_candidates": len(scratch),
            "repository_artifacts": len(artifacts),
            "candidates": len(candidates),
        },
        "scratch_candidates": [
            {
                "relative_path": item["relative_path"],
                "bytes": item["bytes"],
                "extension": item["extension"],
                "modified_at": item["modified_at"],
                "status": "rejected",
                "reason": "scratch_file_requires_explicit_mapping",
            }
            for item in scratch
        ],
        "repository_artifacts_sample": [
            {
                "relative_path": item["relative_path"],
                "bytes": item["bytes"],
                "status": "rejected",
                "reason": "repository_artifact_not_indexed",
            }
            for item in artifacts[:50]
        ],
        "unresolved": unresolved,
        "note": (
            "Conservative discovery only. No scratch or artifact file is parsed or indexed; "
            "each needs an explicit canonical mapping and identity verification."
        ),
    }


# ---------------------------------------------------------------------------
# reading back
# ---------------------------------------------------------------------------


def load_documents(path: Path | str) -> list[dict[str, Any]]:
    """Read a normalized JSONL document store; blank lines are ignored."""
    documents: list[dict[str, Any]] = []
    source = Path(path)
    if not source.is_file():
        return documents
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        documents.append(json.loads(stripped))
    return documents


def load_manifest(state_dir: Path | str) -> dict[str, Any]:
    """Read the working manifest for a private state directory."""
    path = Path(state_dir) / "corpus" / "manifest.json"
    if not path.is_file():
        raise CorpusError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
