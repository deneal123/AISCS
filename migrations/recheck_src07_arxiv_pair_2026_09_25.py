"""Pin current arXiv versions for two 2026 connectome-model cards."""

# ruff: noqa: E501 -- preserve primary version locators and audit caveats.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
VERSIONS = {
    "S286": ("2602.17997", "v3", "2026-06-14"),
    "S741": ("2604.04033", "v1", "2026-04-05"),
}


def updated() -> tuple[dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "src07-version-recheck-audit.json").read_text(encoding="utf-8"))
    for sid, (arxiv_id, version, date) in VERSIONS.items():
        source = next(item for item in records["sources"] if item["id"] == sid)
        url = f"https://arxiv.org/abs/{arxiv_id}"
        if source["издание"] != "arXiv" or source["identifiers"]["exact_url"] != url:
            raise ValueError(f"{sid} current card changed")
        edition = f"arXiv:{arxiv_id}{version}"
        source["издание"] = edition
        source["field_resolution"]["издание"].update({
            "state": "reported", "value": edition,
            "reason": "Current version and submission history checked on the primary arXiv abstract page.",
            "checked_at": DATE,
            "locators": [{"url": url, "locator": f"article header and Submission history: {version}, {date}"}],
        })
        note = f" SRC-07 {DATE}: arXiv lists {version} as the latest version dated {date}; its page provides no journal-ref. This is a version check, not a new full-text validation."
        source["validation"]["notes"] += note
        source["field_resolution"]["validation.notes"].update({
            "state": "reported", "value": source["validation"]["notes"],
            "reason": "Dated primary arXiv version check with scope limited to the arXiv record.",
            "checked_at": DATE,
            "locators": [{"url": url, "locator": "article header, Submission history and journal-ref field"}],
        })
        audit["entries"].append({
            "source_id": sid,
            "current_version": f"arXiv {version}, {date}",
            "source_url": url,
            "access_boundary": "arXiv abstract page and submission history checked; publisher or downstream journal identity is not established solely by an empty journal-ref field",
            "correction_retraction_check": "No arXiv withdrawal notice appears on the checked abstract page; a later notice remains possible.",
            "preprint_journal_relation": "No journal-ref on the checked arXiv page; no journal link asserted.",
        })
    audit["meta"]["scope"] = "SRC-07 six 2026 source-version rechecks"
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = updated()
    if not args.apply:
        print("Dry run: S286 arXiv v3 and S741 arXiv v1")
        return
    snapshot = snapshot_repository(DATA, label="pre-src07-arxiv-pair-recheck")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "src07-version-recheck-audit.json", audit)
    print(f"Rechecked arXiv pair; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
