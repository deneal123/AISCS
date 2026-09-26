"""Pin the scoped adult hemibrain input in S743's author archive."""

# ruff: noqa: E501 -- retain exact archive paths and release boundaries.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
ARTICLE = "https://www.nature.com/articles/s41593-025-02080-4"
CODE = "https://github.com/emebeiran/connconstr/blob/f5f397b88f8dd5c2a5c13558ce6039194a284586/nn_fig5_drosophilaCx_teacher.py#L431-L439"
ARCHIVE = "https://zenodo.org/api/records/16618353/files/Code_NN.zip/content"
README = "Code_NN/Data/Figure5/exported-traced-adjacencies-v1.2/README"


def field(state: str, value: str | None, reason: str, locators: list[dict]) -> dict:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": locators,
    }


def revised() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-connectome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S743")
    entry = next(item for item in audit["entries"] if item["source_id"] == "S743")
    version = entry["extraction"]["connectome_version"]
    if version["state"] != "not_reported" or "input_releases" in entry:
        raise ValueError("S743 version audit differs from expected baseline")
    release = "hemibrain:v1.2"
    version["reason"] = (
        "The published article does not pin all three graph releases. The author Figure 5 code "
        "and archived README identify hemibrain:v1.2 for the adult central-complex input only; "
        "the larval and zebrafish graph releases remain unreported."
    )
    version["checked_at"] = DATE
    version["locators"] = [
        {
            "url": ARTICLE,
            "locator": "Data availability: three source connectomes; Figure 5 adult central-complex example",
        },
        {
            "url": CODE,
            "locator": "Lines 431-439: hemibrain dataset and exported-traced-adjacencies-v1.2 path",
        },
        {
            "url": ARCHIVE,
            "locator": f"Zip internal {README}: neuPrint Client('neuprint.janelia.org', 'hemibrain:v1.2')",
        },
    ]
    entry["input_releases"] = {
        "adult_central_complex_figure5": field(
            "reported",
            release,
            "The author code reads the archived Figure 5 hemibrain adjacency table; its README pins neuPrint hemibrain:v1.2.",
            [
                {"url": CODE, "locator": "Lines 431-439: Figure 5 dataset path"},
                {
                    "url": ARCHIVE,
                    "locator": f"Zip internal {README}, Provenance: neuPrint client and export",
                },
            ],
        ),
        "larval_premotor": field(
            "not_reported",
            None,
            "The checked article names Zarin et al. but gives no release identifier for its larval graph.",
            [{"url": ARTICLE, "locator": "Data availability: Zarin et al. Drosophila larva"}],
        ),
        "larval_zebrafish_brainstem": field(
            "not_reported",
            None,
            "The checked article names Vishwanathan et al. but gives no release identifier for its zebrafish graph.",
            [
                {
                    "url": ARTICLE,
                    "locator": "Data availability: Vishwanathan et al. larval zebrafish brainstem",
                }
            ],
        ),
    }
    entry["archive_evidence"] = {
        "zenodo_doi": "10.5281/zenodo.16618353",
        "archive_file": "Code_NN.zip",
        "archive_md5": "5572648bbaa9eb341c82680ed2390088",
        "readme_path": README,
        "author_code_commit": "f5f397b88f8dd5c2a5c13558ce6039194a284586",
    }
    dataset_key = next(
        key
        for key, item in source["field_resolution"].items()
        if key in source
        and item.get("value") == source[key]
        and isinstance(source[key], str)
        and source[key].startswith("Zarin et al. larval premotor")
    )
    source[dataset_key] += "; Figure 5 adult central-complex code uses neuPrint hemibrain:v1.2"
    resolved = source["field_resolution"][dataset_key]
    resolved["value"] = source[dataset_key]
    resolved["reason"] = (
        "The author code and archived data README pin only the adult central-complex input."
    )
    resolved["checked_at"] = DATE
    resolved["locators"] = version["locators"]
    row = next(item for item in matrix["rows"] if "S743" in item["source_ids"])
    row["limitations"] += (
        " Author data pin hemibrain:v1.2 only for the adult central-complex example; other graph releases remain unverified."
    )
    row["locators"].extend(
        [
            {
                "source_id": "S743",
                "url": CODE,
                "locator": "Lines 431-439: Figure 5 hemibrain v1.2 path",
            },
            {
                "source_id": "S743",
                "url": ARCHIVE,
                "locator": f"Zip internal {README}: neuPrint hemibrain:v1.2 provenance",
            },
        ]
    )
    return records, audit, matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, audit, matrix = revised()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s743-hemibrain-input-release-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "drosophila-connectome-audit.json", audit)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        print(f"Applied scoped S743 release review; snapshot: {snapshot}")
    else:
        print("Dry run: S743 adult input pinned; larval and zebrafish versions remain open")


if __name__ == "__main__":
    main()
