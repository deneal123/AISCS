"""Demote a candidate patent number without an attributable primary record."""

# ruff: noqa: E501 -- preserve exact provenance and exclusion boundaries.

import argparse
import json
from collections import Counter
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
TOPIC = "https://eureka.patsnap.com/topic-patents-autonomic-nervous-system"
DIRECT = "https://patents.google.com/patent/CN122075919A/en"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    ledger = json.loads((DATA / "src07-coverage-ledger-2026-09-25.json").read_text(encoding="utf-8"))
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    source = next(s for s in records["sources"] if s["id"] == "S272")
    assert source["identifiers"]["patent_id"] == "CN122075919A"
    assert source["validation"]["status"] == "verified_metadata"
    assert not any("S272" in r["source_ids"] for r in json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))["rows"])
    note = "A third-party topical index mentions candidate number CN122075919A, but the direct document route and official publication text were not recovered on 2026-09-25. Title, inventors, assignee, abstract and claims remain unidentified. Excluded from evidence pending an attributable primary patent record; this is not proof that the publication does not exist."
    source["validation"].update({
        "status": "rejected", "screening_status": "excluded_unverifiable",
        "checked_at": DATE, "exclusion_reason": "unverifiable", "notes": note,
    })
    source["ограничения"] = note
    source["evidence"]["evidence_role"] = "not_assigned"
    locators = [
        {"url": TOPIC, "locator": "Topical index search snippet mentions CN122075919A without a standalone document or claims"},
        {"url": DIRECT, "locator": "Exact candidate URL returned no attributable document in this dated access attempt"},
    ]
    for key, value, state, reason in (
        ("identifiers.patent_id", "CN122075919A", "reported", "Candidate number observed in a third-party topical index, not verified in an official publication; retained only as a search lead."),
        ("validation.checked_at", DATE, "reported", "Dated primary-route retry and exclusion decision."),
        ("validation.exclusion_reason", "unverifiable", "reported", "No attributable primary patent record was recovered; evidence use is excluded pending retrieval."),
        ("validation.notes", note, "reported", "Dated search result and scientific exclusion boundary."),
        ("ограничения", note, "reported", "Dated search result and scientific exclusion boundary."),
    ):
        source["field_resolution"][key] = {
            "state": state, "value": value, "reason": reason,
            "checked_at": DATE, "locators": locators,
        }
    row = next(r for r in ledger["rows"] if r["source_id"] == "S272")
    assert row["route"] == "primary_route_pending"
    row.update({
        "validation_status": "rejected", "route": "identity_rejected",
        "evidence_artifacts": ["s272-identity-exclusion-2026-09-25.json"],
        "remaining": "Reopen only if an official patent publication with attributable title and text is recovered; candidate number alone supports no claim.",
    })
    ledger["meta"]["route_counts"] = dict(sorted(Counter(r["route"] for r in ledger["rows"]).items()))
    ledger["primary_route_pending_source_ids"] = [r["source_id"] for r in ledger["rows"] if r["route"] == "primary_route_pending"]
    assert ledger["primary_route_pending_source_ids"] == ["S099", "S144", "S245"]
    completeness.update(completeness_summary(records["sources"]))
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE},
        "source_id": "S272", "candidate_patent_id": "CN122075919A",
        "decision": "excluded_unverifiable_until_primary_publication_is_attributed",
        "locators": locators,
        "boundary": note,
    }
    if not args.apply:
        print(f"Dry run: S272 excluded; patent routes pending={ledger['primary_route_pending_source_ids']}")
        return
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    needle = "- [ ] **SRC-08.**"
    assert todo.count(needle) == 1
    todo = todo.replace(needle, "  `S272` переведён из `verified_metadata` в `excluded_unverifiable`: найдено только упоминание кандидатного номера в стороннем тематическом индексе, первичный документ не атрибутирован. Номер сохранён для поиска, но источник исключён из доказательств; реестр SRC-07 теперь оставляет 3 адресных патентных маршрута. См. `data/s272-identity-exclusion-2026-09-25.json`.\n" + needle)
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("- `archive/`", "- `s272-identity-exclusion-2026-09-25.json` — candidate patent identifier excluded from evidence until official attribution;\n- `archive/`")
    snapshot = snapshot_repository(DATA, label="pre-s272-identity-exclusion")
    for name, obj in (("records.json", records), ("src07-coverage-ledger-2026-09-25.json", ledger), ("completeness-report.json", completeness), ("s272-identity-exclusion-2026-09-25.json", audit)):
        atomic_write_json(DATA / name, obj)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Excluded S272 as unverifiable; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
