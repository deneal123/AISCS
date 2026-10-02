"""Tests for the draft corpus module (``corpus.py``).

Run from the repository root, e.g.::

    .venv/Scripts/python.exe -m pytest .work/pi-workers/kb-20261002/corpus/test_corpus.py -q

Every temporary directory is created inside this artifact folder, never in the
repository root and never in ``data/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from service.knowledge import corpus

HERE = Path(__file__).resolve().parent


@pytest.fixture()
def workdir(tmp_path) -> Path:
    return tmp_path


def _write_repo(root: Path, sources: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "records.json").write_text(
        json.dumps({"meta": {"schema_version": "2.0.0"}, "sources": sources}, ensure_ascii=False),
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------


def test_normalize_candidates_merges_and_validates():
    merged = corpus.normalize_candidates(
        [
            {"source_id": "S001", "path": "a.txt", "identity_verified": False},
            {
                "source_id": "S001",
                "primary_url": "https://example.org/a",
                "identity_verified": True,
            },
            {"path": "b.txt"},
        ]
    )
    assert [item["provisional_id"] for item in merged] == ["S001", "local:b.txt"]
    first = merged[0]
    assert first["paths"] == ["a.txt"]
    assert first["primary_urls"] == ["https://example.org/a"]
    assert first["identity_verified_claim"] is True


def test_normalize_candidates_rejects_bad_input():
    with pytest.raises(corpus.CorpusError):
        corpus.normalize_candidates([{"source_id": "bad", "path": "a.txt"}])
    with pytest.raises(corpus.CorpusError):
        corpus.normalize_candidates([{"source_id": "S001"}])
    with pytest.raises(corpus.CorpusError):
        corpus.normalize_candidates("not-a-sequence")


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------


def test_identity_title_and_doi_match():
    text = "A Study of Pain\nDOI: 10.1234/ABC.567\nAbstract\nBody."
    extracted = corpus.extract_identifiers(text)
    ok, evidence = corpus.validate_identity(
        extracted, {"title": "A Study of Pain", "doi": "10.1234/abc.567"}, title="a study of pain"
    )
    assert ok is True
    assert set(evidence["matched"]) >= {"title", "doi"}


def test_identity_accession_match_nct():
    text = "Registered trial NCT01234567 was analysed."
    extracted = corpus.extract_identifiers(text)
    ok, _evidence = corpus.validate_identity(extracted, {"dataset_id": "NCT01234567"}, title=None)
    assert ok is True


def test_identity_filename_alone_never_validates():
    # No title, no DOI, no accession in the parsed document.
    ok, evidence = corpus.validate_identity(
        {
            "doi": [],
            "pmid": [],
            "arxiv_id": [],
            "pmcid": [],
            "nct": [],
            "geo": [],
            "synapse": [],
            "bioproject": [],
        },
        {"title": "S999_10.1234_abc", "doi": "10.1234/abc"},
        title=None,
    )
    assert ok is False
    assert evidence["reason"] in {
        "identity_not_matched",
        "canonical_identity_has_no_comparable_fields",
    }


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------


def test_parse_html_preserves_offsets_pages_sections():
    html = (
        "<html><head><title>Neural Pain Study</title></head><body>"
        "<h2>Abstract</h2><p>We study pain with DOI 10.1234/abc.</p>"
        "<h2>Methods</h2><p>We used ECAP recordings.</p>"
        "</body></html>"
    )
    parsed = corpus.parse_document(html, suffix=".html")
    assert parsed["format"] == "html"
    assert parsed["title"] == "Neural Pain Study"
    assert parsed["needs_ocr"] is False
    text = parsed["text"]
    for section in [{"char_start": 0, "char_end": len(text)}]:
        assert text[section["char_start"] : section["char_end"]] == text
    labels = [label for _offset, label, _raw in parsed["headings"]]
    assert "abstract" in labels
    assert "methods" in labels


def test_parse_xml_extracts_text_and_title():
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<article><front><title-group><article-title>JATS Pain Paper</article-title>"
        "</title-group></front><body><sec><title>Results</title>"
        "<p>Outcome DOI 10.5555/xyz.</p></sec></body></article>"
    )
    parsed = corpus.parse_document(xml, suffix=".nxml")
    assert parsed["format"] == "xml"
    assert "JATS Pain Paper" in parsed["text"]
    assert "Results" in parsed["text"]


def test_parse_txt_plain():
    parsed = corpus.parse_document("Plain text document.\n\nSecond paragraph.")
    assert parsed["format"] == "txt"
    assert parsed["text"].startswith("Plain text document.")


def test_error_and_login_pages_are_detected():
    login = "Sign in to continue\n\nYou must log in to read this article."
    assert corpus.detect_error_page(login) == "error_page_detected"
    parsed = corpus.parse_document(login)
    assert parsed["error_page"] == "error_page_detected"
    assert corpus.detect_error_page("short body", http_status=403) == "error_page_detected"


def test_pdf_without_text_needs_ocr():
    parsed = corpus.parse_document(b"%PDF-1.7\nnot a real pdf\n")
    assert parsed["needs_ocr"] is True
    assert parsed["error"] is not None


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------


def _long_document() -> dict:
    paragraphs = [
        f"Paragraph {i} discusses nociceptive response measurement and ECAP " + ("x" * 200)
        for i in range(40)
    ]
    text = "\n\n".join(paragraphs)
    sections = [{"label": "introduction", "page": 1, "char_start": 0, "char_end": len(text)}]
    return {
        "source_id": "S001",
        "sha256": "a" * 64,
        "version": "v1",
        "page_starts": [0],
        "sections": sections,
        "text": text,
    }


def test_chunk_documents_exact_coordinates_and_stability():
    document = _long_document()
    chunks = corpus.chunk_documents([document])
    assert len(chunks) > 2
    for index, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == index
        assert chunk["chunk_count"] == len(chunks)
        assert chunk["char_start"] < chunk["char_end"]
        assert document["text"][chunk["char_start"] : chunk["char_end"]] == chunk["text"]
        assert chunk["text_sha256"] == corpus._sha256_text(chunk["text"])
        assert chunk["page_start"] == 1
        assert chunk["token_estimate"] <= corpus.CHUNK_TARGET_TOKENS + 50
        assert corpus._sha256_bytes(chunk["text"].encode("utf-8")) == chunk["text_sha256"]
    # Overlap exists between neighbours.
    assert chunks[0]["char_end"] > chunks[1]["char_start"]
    # Stable across repeated calls.
    assert corpus.chunk_documents([document]) == chunks


def test_chunk_section_labels_recorded():
    document = _long_document()
    document["sections"] = [
        {"label": "methods", "page": 1, "char_start": 0, "char_end": len(document["text"]) // 2},
        {
            "label": "results",
            "page": 1,
            "char_start": len(document["text"]) // 2,
            "char_end": len(document["text"]),
        },
    ]
    chunks = corpus.chunk_documents([document])
    labels = {label for chunk in chunks for label in chunk["section_labels"]}
    assert labels <= {"methods", "results"}


def test_chunk_documents_rejects_bad_overlap():
    with pytest.raises(corpus.CorpusError):
        corpus.chunk_documents([], target_tokens=100, overlap_tokens=100)


# ---------------------------------------------------------------------------
# prepare_corpus
# ---------------------------------------------------------------------------


def _candidate_repo(workdir: Path) -> tuple[Path, Path]:
    repo = _write_repo(
        workdir / "repo",
        [
            {
                "id": "S001",
                "название": "Neural Pain Study",
                "identifiers": {
                    "doi": "10.1234/abc",
                    "pmid": None,
                    "arxiv_id": None,
                    "patent_id": None,
                    "dataset_id": None,
                    "exact_url": "https://example.org/s001",
                },
            }
        ],
    )
    html = (
        "<html><head><title>Neural Pain Study</title></head><body>"
        "<h2>Abstract</h2><p>We study pain, DOI 10.1234/abc, with ECAP.</p>"
        "<h2>Methods</h2><p>Methods paragraph.</p>"
        "</body></html>"
    )
    (repo / "paper.html").write_text(html, encoding="utf-8")
    return repo, repo / "paper.html"


def test_prepare_corpus_explicit_candidate_offline(workdir: Path):
    repo, paper = _candidate_repo(workdir)
    state = repo / ".knowledge"
    result = corpus.prepare_corpus(
        repo,
        state,
        candidates=[{"source_id": "S001", "path": paper.name, "identity_verified": False}],
        download=False,
    )
    assert result["counts"]["available"] == 1
    entry = result["manifest"]["entries"][0]
    assert entry["source_id"] == "S001"
    assert entry["status"] == "available"
    assert entry["identity_verified"] is True
    assert entry["sha256"] and entry["version"]
    assert entry["sections"], "sections must be preserved"
    document_path = Path(result["documents_path"])
    assert document_path.is_file()
    documents = corpus.load_documents(document_path)
    assert len(documents) == 1
    stored = Path(result["objects_dir"]) / entry["sha256"]
    assert stored.is_file()
    assert corpus._sha256_bytes(stored.read_bytes()) == entry["sha256"]
    # Nothing canonical was touched.
    assert not (repo / "data").exists()


def test_prepare_corpus_filename_only_identity_is_rejected(workdir: Path):
    repo = _write_repo(
        workdir / "repo2",
        [{"id": "S002", "название": "Real Title", "identifiers": {"doi": "10.9999/real"}}],
    )
    (repo / "S002_10.9999_real.html").write_text(
        "<html><body><h2>Abstract</h2><p>No identifiers in this body.</p></body></html>",
        encoding="utf-8",
    )
    result = corpus.prepare_corpus(
        repo,
        repo / ".knowledge",
        candidates=[{"source_id": "S002", "path": "S002_10.9999_real.html"}],
    )
    entry = result["manifest"]["entries"][0]
    assert entry["status"] == "rejected"
    assert entry["reason"] == "identity_not_matched"
    assert result["counts"]["documents"] == 0


def test_prepare_corpus_error_page_rejected(workdir: Path):
    repo = _write_repo(
        workdir / "repo3",
        [{"id": "S003", "название": "T", "identifiers": {"doi": "10.1/x"}}],
    )
    (repo / "login.html").write_text(
        "<html><body><p>Sign in to continue</p><p>log in to read</p></body></html>",
        encoding="utf-8",
    )
    result = corpus.prepare_corpus(
        repo, repo / ".knowledge", candidates=[{"source_id": "S003", "path": "login.html"}]
    )
    assert result["manifest"]["entries"][0]["status"] == "rejected"
    assert result["manifest"]["entries"][0]["reason"] == "error_page_detected"


def test_prepare_corpus_missing_local_and_url_only_offline(workdir: Path):
    repo = _write_repo(
        workdir / "repo4",
        [
            {"id": "S004", "название": "A", "identifiers": {"doi": "10.1/a"}},
            {"id": "S005", "название": "B", "identifiers": {"doi": "10.1/b"}},
        ],
    )
    result = corpus.prepare_corpus(
        repo,
        repo / ".knowledge",
        candidates=[
            {"source_id": "S004", "path": "missing.html"},
            {"source_id": "S005", "primary_url": "https://example.org/b"},
        ],
        download=False,
    )
    entries = {entry["source_id"]: entry for entry in result["manifest"]["entries"]}
    assert entries["S004"]["status"] == "missing"
    assert entries["S005"]["status"] == "unavailable"
    assert entries["S005"]["reason"] == "download_disabled"


def test_prepare_corpus_http_attempts_capped_and_no_search(workdir: Path, monkeypatch):
    repo = _write_repo(
        workdir / "repo5",
        [
            {
                "id": "S006",
                "название": "C",
                "identifiers": {"doi": "10.1/c", "exact_url": "https://example.org/c"},
            }
        ],
    )
    calls: list[str] = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        return {
            "ok": False,
            "attempts": kwargs.get("max_attempts", 1),
            "status": 503,
            "final_url": url,
            "content_type": None,
            "body": None,
            "error": "http_503",
        }

    monkeypatch.setattr(corpus, "HTTP_FETCHER", fake_fetch)
    result = corpus.prepare_corpus(
        repo,
        repo / ".knowledge",
        candidates=[{"source_id": "S006", "primary_url": "https://example.org/c"}],
        download=True,
    )
    assert calls == ["https://example.org/c"]
    entry = result["manifest"]["entries"][0]
    assert entry["status"] == "unavailable"
    assert entry["reason"] == "http_503"
    assert result["manifest"]["offline"] is False


def test_prepare_corpus_scratch_not_indexed(workdir: Path, monkeypatch):
    repo = _write_repo(
        workdir / "repo6",
        [{"id": "S007", "название": "D", "identifiers": {"doi": "10.1/d"}}],
    )
    scratch = repo / ".work" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "raw_response.html").write_text("<html><body>should not be indexed</body></html>")

    def fail_fetch(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("network must not be used during offline discovery")

    monkeypatch.setattr(corpus, "HTTP_FETCHER", fail_fetch)
    result = corpus.prepare_corpus(repo, repo / ".knowledge", candidates=None, download=False)
    assert result["counts"]["available"] == 0
    assert result["counts"]["documents"] == 0
    assert any(item["relative_path"].endswith("raw_response.html") for item in result["unresolved"])
    report = json.loads(Path(result["scratch_report_path"]).read_text(encoding="utf-8"))
    assert report["counts"]["scratch_candidates"] >= 1
    assert all(item["status"] == "rejected" for item in report["scratch_candidates"])


def test_prepare_corpus_records_registered_primary_urls_without_candidates(workdir: Path):
    repo = _write_repo(
        workdir / "repo7",
        [
            {
                "id": "S008",
                "название": "E",
                "identifiers": {"doi": "10.1/e", "exact_url": "https://example.org/e.pdf"},
            },
            {"id": "S009", "название": "F", "identifiers": {"doi": "10.1/f"}},
        ],
    )
    result = corpus.prepare_corpus(repo, repo / ".knowledge", candidates=None)
    entries = {entry["source_id"]: entry for entry in result["manifest"]["entries"]}
    assert result["counts"]["manifest_entries"] == 2
    assert entries["S008"]["primary_urls"] == ["https://example.org/e.pdf"]
    assert entries["S008"]["reason"] == "no_local_copy_registered_primary_url"
    assert entries["S009"]["primary_urls"] == []
    assert entries["S009"]["reason"] == "no_candidate_locator"
    assert all(entry["status"] == "missing" for entry in entries.values())


def test_registry_is_read_from_data_subdirectory(workdir: Path):
    repo = workdir / "repo8"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "records.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "S010",
                        "название": "From data dir",
                        "identifiers": {"doi": "10.1/g", "exact_url": "https://example.org/g"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = corpus.load_canonical_identity(repo)
    assert registry["S010"]["title"] == "From data dir"
    result = corpus.prepare_corpus(repo, repo / ".knowledge", candidates=None)
    assert result["counts"]["manifest_entries"] == 1
    assert result["counts"]["canonical_sources"] == 1


def test_manifest_entries_have_required_fields(workdir: Path):
    repo = _write_repo(
        workdir / "repo9",
        [{"id": "S011", "название": "G", "identifiers": {"doi": "10.1/h"}}],
    )
    (repo / "g.html").write_text(
        "<html><head><title>G</title></head><body><p>DOI 10.1/h</p></body></html>",
        encoding="utf-8",
    )
    result = corpus.prepare_corpus(
        repo, repo / ".knowledge", candidates=[{"source_id": "S011", "path": "g.html"}]
    )
    required = {
        "source_id",
        "status",
        "reason",
        "primary_urls",
        "sha256",
        "version",
        "retrieved_at",
        "page_count",
        "sections",
    }
    for entry in result["manifest"]["entries"]:
        assert required <= set(entry)
        assert entry["status"] in corpus.MANIFEST_ENTRY_STATUSES
        assert entry["reason"]
    assert result["counts"]["available"] == 1
    assert result["manifest"]["entries"][0]["page_count"] is None


def _data_dir_repo(workdir: Path, name: str) -> Path:
    """Repository whose registry lives at ``<repo>/data/records.json``."""
    repo = workdir / name
    (repo / "data").mkdir(parents=True, exist_ok=True)
    (repo / "data" / "records.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "S001",
                        "название": "Neural Pain Study",
                        "identifiers": {
                            "doi": "10.1234/abc",
                            "exact_url": "https://example.org/s001",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return repo


def test_load_canonical_identity_accepts_repository_object(workdir: Path):
    repo = _data_dir_repo(workdir, "repo-object")

    class Bundle:
        def __init__(self, records: dict) -> None:
            self.records = records

    class FakeRepository:
        def __init__(self, data_dir: Path) -> None:
            self.data_dir = data_dir

        def bundle(self) -> Bundle:
            return Bundle(json.loads((self.data_dir / "records.json").read_text(encoding="utf-8")))

    registry = corpus.load_canonical_identity(FakeRepository(repo / "data"))
    assert registry["S001"]["doi"] == "10.1234/abc"
    result = corpus.prepare_corpus(FakeRepository(repo / "data"), repo / ".knowledge")
    assert result["counts"]["canonical_sources"] == 1
    assert result["repository"] == str(repo.resolve())


def test_load_canonical_identity_accepts_sources_mapping(workdir: Path):
    repo = _data_dir_repo(workdir, "repo-mapping")
    payload = json.loads((repo / "data" / "records.json").read_text(encoding="utf-8"))
    registry = corpus.load_canonical_identity(payload)
    assert registry["S001"]["title"] == "Neural Pain Study"
    with pytest.raises(corpus.CorpusError):
        corpus.prepare_corpus(payload, repo / ".knowledge", candidates=[])


def test_load_canonical_identity_accepts_data_directory_and_records_file(workdir: Path):
    repo = _data_dir_repo(workdir, "repo-paths")
    root_view = corpus.load_canonical_identity(repo)
    assert root_view == corpus.load_canonical_identity(repo / "data")
    assert root_view == corpus.load_canonical_identity(repo / "data" / "records.json")


def test_prepare_corpus_rejects_state_outside_repository(workdir: Path):
    repo, _paper = _candidate_repo(workdir)
    outside = workdir / "outside"
    with pytest.raises(corpus.CorpusError):
        corpus.prepare_corpus(repo, outside, candidates=[])


def test_prepare_corpus_is_deterministic(workdir: Path):
    repo, paper = _candidate_repo(workdir)
    state = repo / ".knowledge"
    first = corpus.prepare_corpus(
        repo, state, candidates=[{"source_id": "S001", "path": paper.name}]
    )
    first_docs = Path(first["documents_path"]).read_text(encoding="utf-8")
    first_chunks = corpus.chunk_documents(corpus.load_documents(first["documents_path"]))
    second = corpus.prepare_corpus(
        repo, state, candidates=[{"source_id": "S001", "path": paper.name}]
    )
    second_docs = Path(second["documents_path"]).read_text(encoding="utf-8")
    second_chunks = corpus.chunk_documents(corpus.load_documents(second["documents_path"]))
    assert first_docs == second_docs
    assert first_chunks == second_chunks
    assert first["manifest"]["entries"][0]["sha256"] == second["manifest"]["entries"][0]["sha256"]


def test_prepare_corpus_resumes_without_source_candidates(workdir: Path):
    repo, paper = _candidate_repo(workdir)
    first = corpus.prepare_corpus(
        repo, repo / ".knowledge", candidates=[{"source_id": "S001", "path": paper.name}]
    )
    paper.unlink()
    second = corpus.prepare_corpus(repo, repo / ".knowledge", candidates=[])
    assert second["counts"]["available"] == 1
    assert second["manifest"]["entries"][0]["sha256"] == first["manifest"]["entries"][0]["sha256"]


def test_prepare_corpus_refuses_unregistered_download_route(workdir: Path):
    repo, _paper = _candidate_repo(workdir)
    with pytest.raises(corpus.CorpusError, match="registered canonical"):
        corpus.prepare_corpus(
            repo,
            repo / ".knowledge",
            candidates=[{"source_id": "S001", "primary_url": "https://unregistered.invalid/paper"}],
            download=True,
        )
