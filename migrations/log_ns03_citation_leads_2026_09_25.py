"""Log bounded backward-citation leads from S212 and S282."""

# ruff: noqa: E501 -- retain exact DOI and relevance boundaries.

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
    stream = next(x for x in protocol["search_streams"] if x["id"] == "NS-03")
    run_id = "NS-RUN-2026-09-25-03"
    if any(x["id"] == run_id for x in protocol["search_runs"]):
        raise ValueError("NS-03 citation run already logged")
    stream["unindexed_primary_leads"].extend(
        [
            {
                "doi": "10.1371/journal.pone.0071706",
                "title": "High-Throughput Analysis of Stimulus-Evoked Behaviors in Drosophila Larva Reveals Multiple Modality-Specific Escape Strategies",
                "url": "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0071706",
                "locator": "Abstract; Figure 2: noxious heat, class IV neurons, rolling and context-dependent escape",
                "status": "primary_full_text_screened_pending_canonical_card",
                "boundary": "Larval behavior and sensory-neuron tests; no brain-wide imaging/EM or subjective pain endpoint.",
            },
            {
                "doi": "10.1073/pnas.1820840116",
                "title": "Drosophila melanogaster foraging regulates a nociceptive-like escape behavior through a developmentally plastic sensory circuit",
                "url": "https://www.pnas.org/doi/10.1073/pnas.1820840116",
                "locator": "Abstract and Results: foraging-dependent larval escape and sensory circuit plasticity",
                "status": "primary_publisher_screened_pending_canonical_card",
                "boundary": "Developmental sensory modulation, not S212's brain-wide network or a human pain measure.",
            },
            {
                "doi": "10.1016/S0092-8674(03)00272-1",
                "title": "painless, a Drosophila Gene Essential for Nociception",
                "url": "https://doi.org/10.1016/S0092-8674(03)00272-1",
                "locator": "Crossref/Europe PMC bibliographic lead and S212/S282 backward references; full primary method remains to be reviewed",
                "status": "bibliographic_lead_pending_full_text_and_canonical_card",
                "boundary": "Foundational molecular nociceptor assay, not a central connectome or subjective pain measure.",
            },
        ]
    )
    stream["coverage_note"] += " Bounded 2026-09-25 backward screening of S212/S282 found three uncatalogued primary leads; their canonical full-text extraction and broader snowballing remain open."
    protocol["search_runs"].append(
        {
            "id": run_id,
            "date": "2026-09-25",
            "queries": [
                "Backward references of S212 DOI 10.1101/2025.09.25.678485",
                "Backward references of S282 DOI 10.1101/2025.09.30.679458",
                "Forward citing works of both seeds in OpenAlex, Europe PMC and Crossref",
            ],
            "primary_urls": [
                "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0071706",
                "https://www.pnas.org/doi/10.1073/pnas.1820840116",
                "https://doi.org/10.1016/S0092-8674(03)00272-1",
            ],
            "new_mechanism_classes": ["modality-specific larval escape", "developmental sensory modulation", "painless molecular nociception"],
            "direct_drosophila_ecap_scs_analogue_found": False,
            "saturation": False,
        }
    )
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-ns03-citation-lead-log")
        atomic_write_json(path, protocol)
        print(f"Logged bounded NS-03 citation leads; snapshot: {snapshot}")
    else:
        print("Dry run: NS-03 citation leads identified, saturation not reached")


if __name__ == "__main__":
    main()
