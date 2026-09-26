"""Reconcile dated SRC-07 evidence across the full 2026 record cohort."""

# ruff: noqa: E501 -- audit boundaries are intentionally explicit.

import argparse
import json
from collections import Counter
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
OUTPUT = DATA / "src07-coverage-ledger-2026-09-25.json"


def read(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = {s["id"]: s for s in read("records.json")["sources"] if s["год"] == 2026}
    sweep = read("src07-crossref-sweep-2026-09-25.json")
    retry = read("src07-crossref-retry-2026-09-25.json")
    crossref = {r["source_id"]: r for r in sweep["rows"]}
    retry_by_id = {r["source_id"]: r for r in retry["rows"]}
    assert len(records) == 81
    assert set(crossref) | set(sweep["non_crossref_route_source_ids"]) == set(records)
    assert not (set(crossref) & set(sweep["non_crossref_route_source_ids"]))
    assert len(crossref) == 50 and len(retry_by_id) == 20
    version = {r["source_id"] for r in read("src07-version-recheck-audit.json")["entries"]}
    code = {r["source_id"] for r in read("src07-code-repository-recheck-2026-09-25.json")["rows"]}
    recovered = {r["source_id"] for r in read("src07-three-source-recovery-2026-09-25.json")["entries"]}
    specific = {
        "S227": "src07-s227-wacv-recheck-2026-09-25.json",
        "S231": "src07-s231-primary-recheck-2026-09-25.json",
    }
    rows = []
    for sid, source in sorted(records.items()):
        evidence = []
        if sid in crossref:
            row = retry_by_id.get(sid, crossref[sid])
            assert row["status"] == "crossref_resolved"
            evidence.append("src07-crossref-retry-2026-09-25.json" if sid in retry_by_id else "src07-crossref-sweep-2026-09-25.json")
            bucket = "crossref_metadata_screened"
            remaining = "Check publisher/primary update and preprint-journal routes; later dated refresh. Empty Crossref relations are not global absence evidence."
        elif source["validation"]["status"] == "rejected":
            bucket = "identity_rejected"
            remaining = "Recheck identity only if new primary lead appears; no publication-version claim can be made from the rejected card."
        else:
            if sid in version:
                evidence.append("src07-version-recheck-audit.json")
            if sid in code:
                evidence.append("src07-code-repository-recheck-2026-09-25.json")
            if sid in recovered:
                evidence.append("src07-three-source-recovery-2026-09-25.json")
            if sid in specific:
                evidence.append(specific[sid])
            bucket = "primary_route_screened" if evidence else "primary_route_pending"
            remaining = ("Later dated refresh and check correction/version relations against the primary owner. Current route is a dated partial check, not global currency proof." if evidence else "Inspect owner or official primary record for current version, correction/retraction and preprint-journal relation.")
        rows.append({
            "source_id": sid, "title": source["название"],
            "validation_status": source["validation"]["status"],
            "route": bucket, "evidence_artifacts": evidence,
            "remaining": remaining,
        })
    counts = dict(sorted(Counter(r["route"] for r in rows).items()))
    assert counts == {
        "crossref_metadata_screened": 50,
        "identity_rejected": 9,
        "primary_route_pending": 7,
        "primary_route_screened": 15,
    }, counts
    result = {
        "meta": {
            "schema_version": "1.0.0", "checked_at": DATE,
            "scope": "SRC-07 complete 2026 source coverage and remaining primary-route queue",
            "total_sources": len(rows), "route_counts": counts,
            "status": "in_progress",
            "boundary": "Registry metadata and dated owner checks do not prove absence of later corrections, retractions or new versions; full primary publisher review and later dated refresh remain open.",
        },
        "rows": rows,
        "primary_route_pending_source_ids": [r["source_id"] for r in rows if r["route"] == "primary_route_pending"],
    }
    if not args.apply:
        print(f"Dry run: {counts}; pending={result['primary_route_pending_source_ids']}")
        return
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    needle = "- [ ] **SRC-08.**"
    assert todo.count(needle) == 1
    note = "  Реестр `data/src07-coverage-ledger-2026-09-25.json` свёл все 81 карточку 2026 года: 50 Crossref-метаданных проверены, 15 отдельных первичных маршрутов просмотрены, 9 карточек отклонены без установленной идентичности; 7 маршрутов (`S099`, `S144`, `S245`, `S253`, `S272`, `S296`, `S368`) остаются непроверенными в этом датированном проходе. Эта классификация не удостоверяет отсутствие позднейших исправлений или новых версий; `SRC-07` открыт.\n"
    todo = todo.replace(needle, note + needle)
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("- `archive/`", "- `src07-coverage-ledger-2026-09-25.json` — complete 2026-source route coverage and seven-item pending primary queue;\n- `archive/`")
    snapshot = snapshot_repository(DATA, label="pre-src07-coverage-ledger")
    atomic_write_json(OUTPUT, result)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Wrote 81-source SRC-07 coverage ledger; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
