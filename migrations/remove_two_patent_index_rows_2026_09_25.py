"""Keep patent index leads out of the primary evidence matrix."""

# ruff: noqa: E501 -- exact audit explanations and locators are kept explicit.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
IDS = {"S144", "S272"}
DATE = "2026-09-25"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    removed = [r for r in matrix["rows"] if set(r["source_ids"]) & IDS]
    assert len(removed) == 2 and {r["source_ids"][0] for r in removed} == IDS
    assert all(len(r["source_ids"]) == 1 for r in removed)
    assert any(s["id"] == "S144" and s["validation"]["status"] == "partially_verified" for s in records["sources"])
    assert any(s["id"] == "S272" and s["validation"]["status"] == "verified_metadata" for s in records["sources"])
    matrix["rows"] = [r for r in matrix["rows"] if not (set(r["source_ids"]) & IDS)]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE},
        "removed_source_ids": sorted(IDS),
        "source_records_retained": True,
        "decision": "S144 has an indexed patent disclosure but no checked official publication text; S272 has only a candidate identifier. Neither supports a positive primary-locator claim in the evidence matrix.",
        "remaining": "Keep both as search leads; restore a technical evidence row only after an official patent publication and exact paragraph/claim locator are checked.",
        "locators": [
            {"source_id": "S144", "url": "https://eureka.patsnap.com/patent/WO2026146221A1", "locator": "Third-party indexed disclosure; WIPO primary text not retrieved"},
            {"source_id": "S272", "url": "https://patents.google.com/patent/CN122075919A/en", "locator": "Exact publication URL unresolved; no primary text or claims retrieved"},
        ],
    }
    if not args.apply:
        print(f"Dry run: remove {sorted(IDS)}; rows={len(matrix['rows'])}")
        return
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    needle = "- [ ] **EVD-04.**"
    assert todo.count(needle) == 1
    todo = todo.replace(needle, "  Две патентные строки `S144` и `S272` убраны из положительной матрицы: первая опиралась на сторонний индекс без проверенного официального текста, вторая содержала только кандидатный номер. Карточки и поисковые ограничения сохранены; восстановление строки требует первичного текста и точного пункта формулы/абзаца. См. `data/two-patent-index-row-removal-2026-09-25.json`. `EVD-03` открыт.\n" + needle)
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("- `archive/`", "- `two-patent-index-row-removal-2026-09-25.json` — removal of two index-only patent leads from positive evidence;\n- `archive/`")
    snapshot = snapshot_repository(DATA, label="pre-two-patent-index-row-removal")
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "two-patent-index-row-removal-2026-09-25.json", audit)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Removed two patent index rows; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
