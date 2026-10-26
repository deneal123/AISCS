"""Two decks share document/: source isolation, slide limit and the weekly progress snapshot."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from service.core import DocumentSidecar, SidecarError, _logged_pages
from service.progress import collect, compress_codes, progress_snapshot, render, tex

ROOT = Path(__file__).resolve().parents[1]


def test_source_excludes_keep_the_two_decks_apart() -> None:
    sidecar = DocumentSidecar(ROOT)
    defence = {p.as_posix() for _, p in sidecar._source_files(sidecar.get_document("PRES-001"))}
    progress = {p.as_posix() for _, p in sidecar._source_files(sidecar.get_document("PRES-002"))}
    assert "document/slides/01-title.tex" in defence
    assert not any(path.startswith("document/progress") for path in defence)
    assert "document/progress/generated/status.tex" in progress
    defence_only = ("document/slides/", "document/presentation.")
    assert not any(path.startswith(defence_only) for path in progress)
    assert "document/config/theme.tex" in defence & progress


def test_slide_limit_blocks_validation(tmp_path: Path) -> None:
    destination = tmp_path / "sidecar"
    shutil.copytree(
        ROOT, destination,
        ignore=shutil.ignore_patterns(".venv", ".pytest_cache", ".ruff_cache", "build", "archive"),
    )
    sidecar = DocumentSidecar(destination)
    defence = sidecar.get_document("PRES-001")
    assert sidecar.slide_count(defence) <= defence["max_slides"]
    extra = defence["max_slides"] - sidecar.slide_count(defence) + 1
    frames = "\n".join(r"\begin{frame}{Extra}\end{frame}" for _ in range(extra))
    (destination / "document/slides/99-extra.tex").write_text(
        frames + "\n% \\begin{frame} commented frames are not counted\n", encoding="utf-8"
    )
    checked = sidecar.validate()
    assert checked["ok"] is False
    assert any("exceed max_slides 20" in error for error in checked["errors"])
    # The progress deck has no limit and does not see the defence slides.
    assert sidecar.slide_count(sidecar.get_document("PRES-002")) >= 1


def test_logged_pages_survive_wrapped_log_lines(tmp_path: Path) -> None:
    log = tmp_path / "deck.log"
    log.write_text(
        "Output written on R:/very/long/path/that/wraps/present\nation.pdf (21 pa\nges).\n",
        encoding="utf-8",
    )
    assert _logged_pages(log) == 21
    assert _logged_pages(tmp_path / "missing.log") is None


def test_build_rejects_pdf_over_the_slide_limit(tmp_path: Path, monkeypatch) -> None:
    sidecar = DocumentSidecar()
    sidecar.root = tmp_path
    document = {"id": "CHECK-001", "entrypoint": "document/deck.tex", "max_slides": 20}
    entry = tmp_path / document["entrypoint"]
    entry.parent.mkdir()
    entry.write_text("source", encoding="utf-8")
    entry.with_suffix(".pdf").write_bytes(b"previous preview")
    monkeypatch.setattr(sidecar, "get_document", lambda document_id: document)
    monkeypatch.setattr(sidecar, "validate", lambda **kwargs: {"ok": True})
    build_dir = tmp_path / "build/check-001"

    def compile_pdf(command, **kwargs):
        (build_dir / "deck.pdf").write_bytes(b"new PDF")
        (build_dir / "deck.log").write_text("Output written on deck.pdf (21 pages).", "utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("service.core.subprocess.run", compile_pdf)
    result = sidecar.build("CHECK-001")
    assert result["ok"] is False and result["pages"] == 21
    assert entry.with_suffix(".pdf").read_bytes() == b"previous preview"


def test_compress_codes_and_tex_escaping() -> None:
    codes = ["EXP-01", "EXP-02", "EXP-03", "CON-05", "REL-01", "REL-02", "SIM-009", "SIM-006"]
    assert compress_codes(codes) == "EXP-01–03, CON-05, REL-01, 02, SIM-006, 009"
    assert tex("G0_REVISE & 50%") == r"G0\_REVISE \& 50\%"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str, *paths: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-10-20T12:00:00+03:00",
        "GIT_COMMITTER_DATE": "2026-10-20T12:00:00+03:00",
    }
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", *paths], check=True)
    subprocess.run([*git, "commit", "-q", "-m", message], check=True, env=env)


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, DocumentSidecar]:
    if shutil.which("git") is None:
        pytest.skip("git is unavailable")
    ws = tmp_path / "workspace"
    research = ws / "research"
    _write(research / "pyproject.toml", '[project]\nversion = "1.6.1"\n')
    _write(research / "TODO.md", "- [x] **SRC-01.** a\n- [ ] **EXP-01.** b\n- [ ] **EXP-02.** c\n")
    data = research / "data"
    _write(data / "records.json", {"sources": [
        {"id": "S001", "validation": {"status": "verified_primary"}},
        {"id": "S002", "validation": {"status": "rejected"}},
    ]})
    _write(data / "aliases.json", {"aliases": {"S900": "S001"}})
    _write(data / "clusters.json", {"clusters": [{}], "retired_clusters": [{}]})
    _write(data / "ST.json", {"categories": [{"подкатегории": [{"ресурсы": [{}, {}]}]}]})
    _write(data / "research/novelty-landscape.json", {
        "meta": {"operational_disposition": {
            "status": "STOP-UNSATURATED", "saturation": False,
            "prior_art_outcome_preserved": "partial_analogues_only",
        }},
        "variants": [{}],
    })
    concept = {"meta": {"gate": "G0_REVISE"}, "tasks": [{}]}
    _write(data / "research/dissertation-concept.json", concept)
    knowledge = research / "knowledge"
    _write(knowledge / "corpus-manifest.json", {"entries": [{"status": "available"}]})
    _write(knowledge / "evaluation-results.json", {"cases": 2, "hits": 2})
    _write(knowledge / "snapshot.json", {"generation": "g-1"})
    _write(knowledge / "library/catalog.json", {"books": [
        {"authors": ["Новиков А. М."], "completeness": "full_text"},
        {"authors": ["Новиков А. М.", "Новиков Д. А."], "completeness": "full_text"},
    ]})
    _write(knowledge / "library/evaluation-results.json", {"cases": 1, "hits": 1})
    _write(knowledge / "library/snapshot.json", {"generation": "g-2"})
    _commit(research, "feat(research): release v1.6.1 fixture", ".")
    text = ws / "materials/text"
    _write(text / "sidecar.json", {"version": "1.1.1"})
    _write(text / "TODO.md", "- [ ] **TXT-02. Согласовать.** a\n- [x] **TXT-01. Каркас:** b\n")
    _write(text / "document/chapters/00-introduction.tex", "Введение и цель % comment\n")
    _write(text / "document/chapters/02-data.tex", "\\section{Данные}\n\\ResultPending{Позже}\n")
    _write(text / "document/backmatter/references.bib", "@article{a,\n}\n@book{b,\n}\n")
    _commit(text, "chore(text): release 1.1.1 fixture", ".")
    publications = ws / "materials/publications"
    _write(publications / "data/publications.json", {"documents": [
        {"id": "PUB-001", "venue": "Конференция (МИН-2026)", "status": "submitted"},
        {
            "id": "PUB-002", "venue": "Журнал", "status": "draft",
            "planned_manuscript_ready": "2026-11",
        },
        {"id": "PUB-TEMPLATE-001", "kind": "template"},
    ]})
    _write(publications / "TODO.md", "11 журнальных и 5 конференционных\n- [ ] **PUBL-01. A.** b\n")
    _write(publications / "sidecar.json", {"version": "1.2.1"})
    _commit(publications, "chore(publications): release 1.2.1 fixture", ".")
    presentation = ws / "materials/presentation"
    for name in ("sidecar.json", "TODO.md", "data", "document"):
        source = ROOT / name
        if source.is_dir():
            shutil.copytree(source, presentation / name, ignore=shutil.ignore_patterns("build"))
        else:
            presentation.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, presentation / name)
    _commit(presentation, "chore(presentation): release 1.1.0 fixture", ".")
    _write(ws / "simulations/data/registry.json", {"candidates": [
        {"id": "SIM-001", "role": "neural", "evaluation": {"status": "reproduced"}},
        {"id": "SIM-002", "role": "embodied", "evaluation": {"status": "blocked"}},
    ]})
    _write(ws / "simulations/data/assessment.json", {"candidates": [
        {"id": "SIM-001", "checks": [{"id": "visuals", "status": "passed"}]},
        {"id": "SIM-002", "checks": [], "biological_validation": False},
    ]})
    _commit(ws, "chore: fixture workspace", "simulations")
    return ws, DocumentSidecar(presentation)


def test_progress_snapshot_counts_and_reproducibility(workspace) -> None:
    ws, sidecar = workspace
    as_of = date(2026, 10, 26)
    payload = collect(sidecar, ws, as_of=as_of)
    assert payload["research"]["sources"] == 2
    assert payload["research"]["todo"] == {
        "done": 1, "open": 2, "total": 3, "open_codes": ["EXP-01", "EXP-02"],
    }
    assert payload["library"]["authors"] == ["Новиков (2)"]
    by_status = payload["simulations"]["by_status"]
    assert by_status == {"blocked": ["SIM-002"], "reproduced": ["SIM-001"]}
    assert payload["history"]["week_commits"]["research"] == 1
    assert {item["version"] for item in payload["history"]["releases"]} >= {"1.6.1", "1.1.1"}
    assert payload["uncommitted_sources"] == []
    status = render(payload)
    assert r"\newcommand{\ProgSources}{2}" in status
    assert r"\newcommand{\ProgGate}{G0\_REVISE}" in status
    assert "EXP-01, 02" in status and "Глава 2 & 2 & 1" in status
    assert r"PUB-002 & Журнал & Черновик & 11.2026 \\\hline" in status
    config = json.loads((ROOT / "sidecar.json").read_text(encoding="utf-8"))
    assert not any(re.search(pattern, status) for pattern in config["placeholder_patterns"])

    first = progress_snapshot(sidecar, ws, as_of=as_of, apply=True)
    written = (sidecar.root / "document/progress/generated/status.tex").read_text("utf-8")
    snapshot = (sidecar.root / "data/progress-snapshot.json").read_text("utf-8")
    progress_snapshot(sidecar, ws, as_of=as_of, apply=True)
    assert first["applied"] is True and written == status
    assert (sidecar.root / "data/progress-snapshot.json").read_text("utf-8") == snapshot

    (ws / "simulations/data/registry.json").write_text('{"candidates": []}', encoding="utf-8")
    assert collect(sidecar, ws, as_of=as_of)["uncommitted_sources"] == [
        "simulations/data/registry.json"
    ]


def test_progress_snapshot_requires_the_workspace(tmp_path: Path) -> None:
    with pytest.raises(SidecarError, match="workspace not found"):
        collect(DocumentSidecar(ROOT), tmp_path)
