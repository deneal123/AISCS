"""Keep EVOKE primary reports visible pending separate canonical extraction."""

# ruff: noqa: E501 -- exact cohort and outcome distinctions are important.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    path = DATA / "search-protocol.json"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    stream = next(x for x in protocol["search_streams"] if x["id"] == "NS-10")
    if "unindexed_primary_leads" in stream:
        raise ValueError("NS-10 leads already logged")
    stream["unindexed_primary_leads"] = [
        {
            "doi": "10.1016/S1474-4422(19)30414-4",
            "title": "Long-term safety and efficacy of closed-loop spinal cord stimulation to treat chronic back and leg pain (Evoke)",
            "url": "https://pubmed.ncbi.nlm.nih.gov/31870766/",
            "locator": "Primary PubMed abstract: 134 randomized; 118 in 12-month ITT analysis; >=50% overall back/leg pain reduction without increased medication",
            "status": "primary_abstract_screened_pending_canonical_card; full Lancet methods subscription gated",
            "boundary": "ECAP-controlled stimulation is the intervention; clinical pain is a separate patient-reported endpoint.",
        },
        {
            "doi": "10.1001/jamaneurol.2021.4998",
            "title": "Durability of Clinical and Quality-of-Life Outcomes of Closed-Loop Spinal Cord Stimulation for Chronic Back and Leg Pain",
            "url": "https://jamanetwork.com/journals/jamaneurology/fullarticle/2788004",
            "locator": "Abstract; Methods; Figure 1 CONSORT; Results: 24-month secondary analysis of the same EVOKE RCT, 134 randomized in primary-outcome analysis with missing values carried forward, 92 completers for secondary outcomes",
            "status": "primary_full_text_screened_pending_canonical_card; Figure 4 correction must be linked",
            "boundary": "Same NCT02924129 cohort as the 12-month paper, not an independent trial or prospective pain-prediction model.",
            "correction_doi": "10.1001/jamaneurol.2022.0022",
        },
    ]
    stream["coverage_note"] = "Two primary EVOKE reports found on 2026-09-25. They are the same randomized cohort; 12-month Lancet full text is gated, 24-month JAMA full text is open and has a Figure 4 correction. Canonical extraction and broader snowballing remain open."
    protocol["search_runs"].append(
        {
            "id": "NS-RUN-2026-09-25-04",
            "date": "2026-09-25",
            "queries": ["Evoke ECAP closed-loop randomized trial 12 month Mekhail", "Evoke 24 month NCT02924129 JAMA Neurology secondary analysis", "10.1016/S1474-4422(19)30414-4 and 10.1001/jamaneurol.2021.4998 duplicate check"],
            "primary_urls": ["https://pubmed.ncbi.nlm.nih.gov/31870766/", "https://jamanetwork.com/journals/jamaneurology/fullarticle/2788004", "https://doi.org/10.1001/jamaneurol.2022.0022"],
            "new_mechanism_classes": ["ECAP-controlled randomized SCS dosing with patient-reported pain outcome"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns10-evoke-primary-leads")
        atomic_write_json(path, protocol)
        print(f"Logged EVOKE primary leads; snapshot: {snapshot}")
    else:
        print("Dry run: EVOKE same-cohort primary leads pending canonical extraction")


if __name__ == "__main__":
    main()
