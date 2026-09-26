"""Correct three larval nociception source stages and expand NS-03 coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
CORRECTIONS = {
    "S030": (
        "https://www.nature.com/articles/nn.4580",
        "Abstract, first two sentences: Drosophila melanogaster larvae "
        "and mechanonociceptive escape",
    ),
    "S092": (
        "https://elifesciences.org/articles/95379",
        "Abstract, final two sentences: larval acute and subsequent mechanical responses",
    ),
    "S154": (
        "https://www.mdpi.com/2306-5729/10/2/11",
        "Abstract and Section 2.1: third-instar larvae, UV injury and nociceptor translatome",
    ),
}
NS03_IDS = [
    "S012", "S013", "S026", "S027", "S029", "S030", "S031", "S065",
    "S066", "S090", "S092", "S152", "S154", "S212", "S282",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    records_path = DATA / "records.json"
    protocol_path = DATA / "search-protocol.json"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in records["sources"]}
    for source_id, (url, locator) in CORRECTIONS.items():
        source = sources[source_id]
        if source["evidence"]["subject_domain"] != "drosophila_adult":
            raise ValueError(f"unexpected original stage for {source_id}")
        source["evidence"]["subject_domain"] = "drosophila_larva"
        source["evidence"]["species"] = "Drosophila melanogaster"
        for field, value in (
            ("evidence.subject_domain", "drosophila_larva"),
            ("evidence.species", "Drosophila melanogaster"),
        ):
            source["field_resolution"][field] = {
                "state": "reported",
                "value": value,
                "reason": "Primary article identifies the preparation as Drosophila larvae.",
                "checked_at": "2026-09-24",
                "locators": [{"url": url, "locator": locator}],
            }

    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-03")
    stream["source_ids"] = NS03_IDS
    stream["coverage_note"] = (
        "Existing canonical candidates include primary experiments, a protocol, a dataset "
        "description and reviews; inclusion is for screening, not equivalent evidence. "
        "Stimulus, neural response and behavior still require source-specific extraction."
    )
    stream["unindexed_primary_leads"] = [
        {
            "title": (
                "Descending GABAergic pathway links brain sugar-sensing to "
                "peripheral nociceptive gating in Drosophila"
            ),
            "url": "https://www.nature.com/articles/s41467-023-42202-9",
            "locator": (
                "Abstract and Figure 2: larval mechanical and chemical nociception, "
                "optogenetic gating and rolling"
            ),
            "status": "primary_full_text_found_canonical_card_pending",
        },
        {
            "title": (
                "Nociceptive interneurons control modular motor pathways "
                "to promote escape behavior in Drosophila"
            ),
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5869015/",
            "locator": (
                "Abstract and Results: larval nociceptor activation and "
                "divergent escape motor outputs"
            ),
            "status": "primary_full_text_found_canonical_card_pending",
        },
    ]

    if not args.apply:
        print(json.dumps({"corrected": list(CORRECTIONS), "ns03_candidates": len(NS03_IDS)}))
        return 0
    snapshot = snapshot_repository(DATA, label="pre-drosophila-nociception-stage-correction")
    atomic_write_json(records_path, records)
    atomic_write_json(protocol_path, protocol)
    completeness_path = DATA / "completeness-report.json"
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    atomic_write_json(completeness_path, completeness)
    print(json.dumps({"snapshot": str(snapshot), "corrected": list(CORRECTIONS)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
