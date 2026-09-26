"""Replace broad staging locators on S782/S783 with primary text sections."""

# ruff: noqa: E501 -- preserve exact primary section names in field locators.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
SPECS = {
    "S782": {
        "pmcid": "PMC13314972",
        "pmid": "42026054",
        "map": {
            "модальность": "Abstract; Results > Simulating a connectome-derived antennal grooming network; Figure 5A-B",
            "задача": "Abstract; Results > Simulating a connectome-derived antennal grooming network",
            "метод": "Methods > Connectome-constrained neural network modeling; Model parameters and training",
            "датасет": "Methods > Connectome analysis, first paragraph; Optogenetic training dataset",
            "производительность": "Results > Simulating a connectome-derived antennal grooming network; Figure 5B; Supplementary Figure 10C",
            "ограничения": "Results > Figure 5A; Discussion; Methods > Connectome analysis",
            "evidence.population": "Methods > Fly stocks; Connectome analysis",
            "evidence.sample_size": "Results > Simulating a connectome-derived antennal grooming network, n=10; Methods > training dataset",
            "evidence.target_label": "Results > Figure 5A-B, head and antennal pitch kinematics",
        },
    },
    "S783": {
        "pmcid": "PMC11446846",
        "pmid": "39358520",
        "map": {
            "модальность": "Abstract; Results > Figure 3 and Figure 5; Methods > Connectome-constrained modelling",
            "задача": "Abstract, walk-OFF and brake mechanisms",
            "метод": "Methods > Connectome-constrained modelling, Brian2 v2.5.1 and FlyWire connectivity",
            "датасет": "Methods > Identification of neurons in connectome; Connectome-constrained modelling; Supplementary Table 1",
            "производительность": "Results > Figure 5a-h; Extended Data Figure 9; Methods > Connectome-constrained modelling",
            "ограничения": "Abstract; Discussion; Results > context-specific halting",
            "evidence.population": "Methods > Fly husbandry; Identification of neurons in connectome",
            "evidence.sample_size": "Figure 5 legend; Supplementary Table 1, assay-specific denominators",
            "evidence.target_label": "Abstract; Results > Figure 3 and Figure 5, walking halt",
        },
    },
}


def locator(path: str, spec: dict) -> tuple[str, str]:
    pmc = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{spec['pmcid']}/fullTextXML"
    if path.startswith("provenance."):
        return "local:data/search-protocol.json", "NS-04 stream and NS-RUN-2026-09-25-07"
    if path in {"validation.checked_at", "validation.exclusion_reason"}:
        return "local:data/drosophila-connectome-audit.json", "S782/S783 extraction dated 2026-09-25"
    if path == "identifiers.pmid":
        return f"https://pubmed.ncbi.nlm.nih.gov/{spec['pmid']}/", "PMID and DOI under article citation"
    if path in {"авторы", "год", "издание", "identifiers.doi", "identifiers.exact_url"}:
        return pmc, "Article front matter: title, author group, citation, publication date and DOI"
    if path.startswith("identifiers."):
        return pmc, "Article front matter and supplementary metadata: no such identifier assigned"
    if path in spec["map"]:
        return pmc, spec["map"][path]
    if path.startswith("evidence."):
        return pmc, "Abstract; Results; Methods, organism, assays and measured variables"
    if path.startswith("validation."):
        return pmc, "Methods > model comparison and experimental validation; Discussion, scope limits"
    if path == "кросс_субъект":
        return pmc, "Methods > connectome model and fly assays; no human participant prediction"
    return pmc, "Abstract; Results; Methods"


def updated() -> dict:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    for sid, spec in SPECS.items():
        source = next(item for item in records["sources"] if item["id"] == sid)
        for path, resolution in source["field_resolution"].items():
            url, section = locator(path, spec)
            resolution["locators"] = [{"url": url, "locator": section}]
            resolution["checked_at"] = DATE
            if resolution["state"] == "reported" and not path.startswith("provenance."):
                resolution["reason"] = "Checked against the primary article at the cited section; clinical transfer is outside the source scope."
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = updated()
    if not args.apply:
        print("Dry run: exact section locators for S782/S783")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns04-card-locator-strengthening")
    atomic_write_json(DATA / "records.json", records)
    print(f"Strengthened S782/S783 locators; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
