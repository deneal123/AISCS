import json
from pathlib import Path

import pytest

from scripts import check_release
from service.data_layout import DATA_PATHS, data_path

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def release_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    for relative in DATA_PATHS.values():
        (data / relative).parent.mkdir(parents=True, exist_ok=True)
        (data / relative).write_text("{}", encoding="utf-8")
    (tmp_path / "docs" / "audits").mkdir(parents=True)
    for name, payload in {
        "records.json": {"sources": []},
        "aliases.json": {"aliases": {}},
        "clusters.json": {"clusters": [], "retired_clusters": []},
    }.items():
        (data_path(data, name)).write_text(json.dumps(payload), encoding="utf-8")
    for name in ("TODO.md", "README.md", "SKILL.md", "data/README.md"):
        (tmp_path / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(check_release, "ROOT", tmp_path)
    monkeypatch.setattr(check_release, "DATA", data)
    monkeypatch.setattr(check_release, "MANIFEST", data_path(data, "release-manifest.json"))
    return tmp_path


def test_release_inventory_covers_agent_instructions_without_frozen_copies(
    release_tree: Path,
) -> None:
    for area in ("archive", "provenance", "staging"):
        path = release_tree / "data" / area / "frozen.json"
        path.parent.mkdir()
        path.write_text("{}", encoding="utf-8")
    paths = {p.relative_to(release_tree).as_posix() for p in check_release.current_files()}
    assert {"README.md", "SKILL.md", "TODO.md"} <= paths
    assert not any("frozen.json" in p for p in paths)


def test_release_rejects_crlf_without_touching_frozen_originals(release_tree: Path) -> None:
    current = release_tree / "README.md"
    current.write_bytes(b"current\r\n")
    frozen = release_tree / "data" / "archive" / "original.json"
    frozen.parent.mkdir()
    frozen.write_bytes(b"{}\r\n")
    assert check_release.check_line_endings() == [
        "README.md: current release text must use LF line endings"
    ]
    current.write_bytes(b"current\n")
    assert check_release.check_line_endings() == []
    assert frozen.read_bytes() == b"{}\r\n"


def test_release_rejects_stale_skill_reference(release_tree: Path) -> None:
    skill = release_tree / "SKILL.md"
    skill.write_text("[Contract](docs/data-contract.md)", encoding="utf-8")
    assert "SKILL.md: missing link docs/data-contract.md" in check_release.check_links_and_ids()
    target = release_tree / "docs" / "reference" / "data-contract.md"
    target.parent.mkdir()
    target.write_text("# Contract\n", encoding="utf-8")
    skill.write_text("[Contract](docs/reference/data-contract.md)", encoding="utf-8")
    assert check_release.check_links_and_ids() == []


def test_release_rejects_missing_task_anchor(release_tree: Path) -> None:
    ledger = release_tree / "docs" / "audits" / "todo-decision-ledger.md"
    ledger.write_text("## SRC-01\n", encoding="utf-8")
    todo = release_tree / "TODO.md"
    todo.write_text("[History](docs/audits/todo-decision-ledger.md#src-01)", encoding="utf-8")
    assert check_release.check_links_and_ids() == []
    ledger.write_text("## SRC-02\n", encoding="utf-8")
    assert any("missing anchor" in error for error in check_release.check_links_and_ids())


@pytest.mark.parametrize("damage", ["missing_ledger_section", "duplicate_task"])
def test_release_rejects_lost_or_duplicate_task(
    release_tree: Path, damage: str,
) -> None:
    todo = release_tree / "TODO.md"
    ledger = release_tree / "docs" / "audits" / "todo-decision-ledger.md"
    todo.write_bytes((ROOT / "TODO.md").read_bytes())
    ledger.write_bytes((ROOT / "docs/audits/todo-decision-ledger.md").read_bytes())
    assert check_release.check_todo_ledger() == []
    if damage == "missing_ledger_section":
        ledger.write_text(ledger.read_text(encoding="utf-8").replace("## SRC-01\n", "## Removed\n"), encoding="utf-8")
    else:
        todo.write_text(todo.read_text(encoding="utf-8").replace("**SRC-02.**", "**SRC-01.**"), encoding="utf-8")
    assert check_release.check_todo_ledger()


def test_release_checks_reusable_primary_links(release_tree: Path) -> None:
    path = release_tree / "README.md"
    path.write_text("[History][primary-1]\n\n[primary-1]: docs/missing.md\n", encoding="utf-8")
    assert "README.md: missing link docs/missing.md" in check_release.check_links_and_ids()
    target = release_tree / "docs" / "missing.md"
    target.write_text("# Found\n", encoding="utf-8")
    assert check_release.check_links_and_ids() == []


def test_release_rejects_undefined_primary_reference(release_tree: Path) -> None:
    (release_tree / "README.md").write_text("[Primary text][primary-1]\n", encoding="utf-8")
    assert "README.md: undefined reference label primary-1" in check_release.check_links_and_ids()


@pytest.mark.parametrize("damage", ["stale_count", "cutoff", "completed_audit", "saturation"])
def test_release_rejects_current_state_drift(release_tree: Path, damage: str) -> None:
    data = release_tree / "data"
    sources = {"sources": [{"id": "S001"}]}
    (data_path(data, "records.json")).write_text(json.dumps(sources), encoding="utf-8")
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    (release_tree / "TODO.md").write_text(todo, encoding="utf-8")
    report = "содержит 1 карточек и 0 алиас; — 0 активных и 0 исторических. **35/43**"
    (release_tree / "docs/final-validation-report.md").write_text(report, encoding="utf-8")
    decision = {"date": "2026-10-01", "search_saturation": False,
                "decision": "bounded_search_accepted_at_cutoff"}
    search = {"meta": {"cutoff": "2026-10-01", "status": "bounded_research_cutoff_accepted"},
              "pa_saturation_log_2026_10_01": {"pa08_author_bounded_cutoff_2026_10_01": decision}}
    (data_path(data, "search-protocol.json")).write_text(json.dumps(search), encoding="utf-8")
    (data_path(data, "novelty-landscape.json")).write_text(json.dumps({"meta": {"cutoff": "2026-10-01"}}), encoding="utf-8")
    for name in (
        "pa01-s775-s782-citation-pass-2026-09-25.json", "ns04-perturbation-model-audit.json",
        "ecap-trial-registry-audit.json", "ns15-russian-prior-art-audit.json",
        "forbidden-transfer-audit-2026-09-25.json",
    ):
        payload = {"meta": {"status": "bounded_complete", "latest_cutoff": "2026-09-30"}}
        (data_path(data, name)).write_text(json.dumps(payload), encoding="utf-8")
    assert check_release.check_current_state() == []
    if damage == "stale_count":
        (release_tree / "docs/final-validation-report.md").write_text(report.replace("1 карточек", "2 карточек"), encoding="utf-8")
    elif damage == "cutoff":
        search["meta"]["cutoff"] = "2026-09-25"
        (data_path(data, "search-protocol.json")).write_text(json.dumps(search), encoding="utf-8")
    elif damage == "completed_audit":
        path = data_path(data, "ecap-trial-registry-audit.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["meta"]["status"] = "in_progress"
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        decision["search_saturation"] = True
        (data_path(data, "search-protocol.json")).write_text(json.dumps(search), encoding="utf-8")
    assert check_release.check_current_state()


@pytest.mark.parametrize("damage", ["total", "statuses", "level", "batches", "workflow", "closed_gate"])
def test_release_recounts_data_summaries(release_tree: Path, damage: str) -> None:
    data = release_tree / "data"
    for name in ("records.json", "aliases.json", "clusters.json", "ST.json", "audit-report.json", "validation-log.json"):
        (data_path(data, name)).write_bytes(data_path(ROOT / "data", name).read_bytes())
    (release_tree / "TODO.md").write_bytes((ROOT / "TODO.md").read_bytes())
    assert check_release.check_corpus_summaries() == []
    audit = json.loads((data_path(data, "audit-report.json")).read_text(encoding="utf-8"))
    if damage == "total":
        audit["current_corpus"]["canonical_sources"] -= 1
    elif damage == "statuses":
        audit["current_corpus"]["validation_statuses"]["verified_primary"] -= 1
    elif damage == "level":
        audit["current_curation"]["by_relevance"]["3"]["canonical_count"] -= 1
    elif damage == "batches":
        audit["current_curation"]["applied_batches"].pop()
    elif damage == "closed_gate":
        audit["remaining_gates"].append("PA-08 completion still required")
    else:
        path = data_path(data, "validation-log.json")
        log = json.loads(path.read_text(encoding="utf-8"))
        log["meta"]["status"] = "all_source_validation_complete_author_review_pending"
        path.write_text(json.dumps(log), encoding="utf-8")
    (data_path(data, "audit-report.json")).write_text(json.dumps(audit), encoding="utf-8")
    assert check_release.check_corpus_summaries()


@pytest.mark.parametrize("damage", ["raw_json", "extra_original", "published_candidate", "old_path"])
def test_release_rejects_data_clutter(release_tree: Path, damage: str) -> None:
    data = release_tree / "data"
    (data / "README.md").write_text(
        "\n".join(f"[{name}]({relative.as_posix()})" for name, relative in DATA_PATHS.items()),
        encoding="utf-8",
    )
    for scope in check_release.SCOPES:
        base = data / "curation" / scope
        base.mkdir(parents=True)
        (base / "applied-batches.json").write_text('{"entries": {}}', encoding="utf-8")
    assert check_release.check_layout() == []
    if damage == "raw_json":
        path = data / "worker-answer.json"
        path.write_text("{}", encoding="utf-8")
    elif damage == "extra_original":
        path = data / "provenance/applied-batches/relevance-5/extra.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}", encoding="utf-8")
    elif damage == "old_path":
        (data / "vocabularies.json").write_text("{}", encoding="utf-8")
    else:
        candidate = {"id": "S001", "title": "Published"}
        (data_path(data, "records.json")).write_text(json.dumps({"sources": [candidate]}), encoding="utf-8")
        path = data / "staging/inbox/candidate.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(candidate), encoding="utf-8")
    assert check_release.check_layout()
