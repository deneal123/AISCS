"""Keep repository-only simulations distinct from biological comparators."""

# ruff: noqa: E501 -- exact repository locators and screening reasons are kept together.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
CODE = {
    "S200": (
        "https://github.com/nftechie/doomfly/tree/71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33",
        "README, model loop and validation status: MaleCNS v1.0 Doom controller; v6 fails its own visual, conditioning and survival gates",
        "Code and simulated behavior only; no measured biological activity comparator. Retain as an engineering resource, not a second independent connectome experiment.",
    ),
    "S292": (
        "https://github.com/legacyindiesubmissions-ai/claude-fly/tree/3a035275148e97539711728422548bffe2a77566",
        "README, Paper: repository explicitly accompanies Zenodo DOI 10.5281/zenodo.19152238, canonical paper S320",
        "Companion code for S320, not an independent replication cohort or second study; inspect the paper under S320 for methods and result claims.",
    ),
    "S737": (
        "https://github.com/gauravvvvvvvvvv/flybox/tree/a2bd9bc034d9ed887efc4c14b513512845be5f86",
        "README, Scientific provenance: FlyBrain/MaleCNS browser export and experimental encoders/decoders; biological simulation disclaimers",
        "Interactive code sandbox with engineered input/output mappings and no matched measured biological comparator; retain as a resource, not a validation study.",
    ),
}


def update() -> tuple[dict, dict]:
    records_path = DATA / "records.json"
    audit_path = DATA / "drosophila-connectome-audit.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("screened_code_resources"):
        raise ValueError("Code resources already screened")
    if not any(item["source_id"] == "S320" for item in audit["entries"]):
        raise ValueError("S320 paper audit must exist first")
    sources = {source["id"]: source for source in records["sources"]}
    audit["screened_code_resources"] = [
        {
            "source_id": source_id,
            "disposition": "resource_only_not_independent_biological_comparator",
            "reason": reason,
            "checked_at": DATE,
            "locators": [{"url": url, "locator": locator}],
        }
        for source_id, (url, locator, reason) in CODE.items()
    ]
    sources["S292"]["relations"].append({
        "type": "code_for",
        "target_id": "S320",
        "external_id": None,
        "note": "Repository README cites the same Zenodo preprint DOI; its outputs are not independent replication evidence.",
    })
    return records, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit = update()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-connectome-code-resource-screen")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        print(f"Applied code-resource screen; snapshot: {snapshot}")
    else:
        print("Dry run: S200, S292 and S737 screened; S292 linked to S320")


if __name__ == "__main__":
    main()
