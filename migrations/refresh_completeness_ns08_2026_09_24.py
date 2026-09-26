"""Synchronize the materialized completeness report after S765 curation."""

import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    path = DATA / "completeness-report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    summary = completeness_summary(records["sources"])
    if summary["records"] != 173 or summary["unresolved_count"]:
        raise ValueError("Unexpected corpus size or unresolved fields")
    report.update(summary)
    snapshot = snapshot_repository(DATA, label="pre-ns08-completeness-refresh")
    atomic_write_json(path, report)
    print(f"Refreshed completeness report; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
