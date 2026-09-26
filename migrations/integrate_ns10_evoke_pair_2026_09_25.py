"""Index EVOKE trial reports as one cohort and preserve the ECAP/outcome boundary."""

# ruff: noqa: E501 -- primary outcome and correction locators are precise.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
LANCET = "https://pubmed.ncbi.nlm.nih.gov/31870766/"
JAMA = "https://jamanetwork.com/journals/jamaneurology/fullarticle/2788004"
CORRECTION = "https://jamanetwork.com/journals/jamaneurology/fullarticle/2789149"
DOIS = {
    "10.1016/S1474-4422(19)30414-4": "S779",
    "10.1001/jamaneurol.2021.4998": "S780",
}


def field(state: str, value: str | None, url: str, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": state, "value": value,
        "reason": "Clinical endpoint and intervention/control signal are separate; no prognostic prediction model is tested." if boundary else "Extracted from the named primary text.",
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


ENTRIES = [
    {
        "source_id": "S779",
        "extraction": {
            "input_role": field("reported", "Implanted ECAP-controlled closed-loop SCS is the randomized intervention; ECAP is the feedback signal for stimulation amplitude, not a baseline prognostic predictor or pain readout.", LANCET, "Author abstract, Methods: closed-loop versus fixed-output open-loop stimulation", boundary=True),
            "target_role": field("reported", "At least 50% reduction in overall back-and-leg pain without increased pain medication at 3 months (primary) and 12 months (prespecified additional analysis).", LANCET, "Author abstract, Methods and Findings"),
            "study_design": field("reported", "Double-blind, randomized 1:1 trial NCT02924129 at 13 US sites; 134 randomized (67/67); 125 analyzed at 3 months and 118 at 12 months.", LANCET, "Author abstract, Methods and Findings"),
            "prognostic_validation": field("not_applicable", None, LANCET, "Author abstract: treatment-arm efficacy trial, no preimplant patient-outcome prediction model", boundary=True),
        },
    },
    {
        "source_id": "S780",
        "extraction": {
            "input_role": field("reported", "ECAP-guided closed-loop stimulation is the therapy arm and device-control signal; open-loop SCS is the randomized comparator, not a learned predictor.", JAMA, "Methods, Interventions; Figure 4 device performance", boundary=True),
            "target_role": field("reported", "Patient-reported overall back-and-leg pain reduction of at least 50% (responder) or 80% (high responder) at 24 months; quality-of-life and function are secondary outcomes.", JAMA, "Abstract, Main Outcomes and Measures; Results, Figure 2 and Table"),
            "study_design": field("reported", "Secondary analysis of the same NCT02924129 trial as S779: 134 randomized (67/67) included for primary pain outcome with last observation carried forward; 50 closed-loop and 42 open-loop patients completed the 24-month visit for secondary outcomes.", JAMA, "Methods; Figure 1 CONSORT legend"),
            "prognostic_validation": field("not_applicable", None, JAMA, "Methods: randomized therapy comparison and 24-month outcomes, not a preimplant predictive model", boundary=True),
        },
    },
]


def updated() -> tuple[dict, dict, dict, str]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    canonical = {r["id"]: r for r in records["sources"]}
    if any(canonical[source_id]["identifiers"]["doi"].lower() != doi.lower() for doi, source_id in DOIS.items()):
        raise ValueError("Publish EVOKE cards before audit integration")
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "scs-outcome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    stream = next(s for s in protocol["search_streams"] if s["id"] == "NS-10")
    if {lead["doi"].lower() for lead in stream["unindexed_primary_leads"]} != {doi.lower() for doi in DOIS}:
        raise ValueError("Expected two pending EVOKE leads")
    if {"S779", "S780"} & {e["source_id"] for e in audit["entries"]}:
        raise ValueError("EVOKE already in outcome audit")
    indexed = []
    for lead in stream["unindexed_primary_leads"]:
        item = {**lead, "source_id": DOIS[lead["doi"]], "status": "canonical_card_and_outcome_audit_recorded"}
        indexed.append(item)
    stream["source_ids"] = sorted([*stream["source_ids"], "S779", "S780"])
    stream["unindexed_primary_leads"] = []
    stream.setdefault("indexed_primary_leads", []).extend(indexed)
    stream["coverage_note"] = "EVOKE 3/12-month Lancet (S779) and 24-month JAMA (S780) reports are indexed as one randomized cohort, NCT02924129. The Lancet method is abstract-only here; JAMA full text distinguishes 134 randomized primary-outcome records from 92 24-month completers, and its Figure 4 has a correction. ECAP is feedback for the intervention, not a pain measure or baseline outcome predictor. Broader snowballing remains open."
    audit["entries"].extend(ENTRIES)
    audit["entries"].sort(key=lambda e: e["source_id"])
    audit["meta"].update({"generated_at": DATE, "records_count": len(audit["entries"])})
    audit.setdefault("study_families", []).append({
        "trial_id": "NCT02924129", "source_ids": ["S779", "S780"],
        "decision": "One randomized cohort with 3/12- and 24-month reports; count as one trial, not two independent validations.",
        "locators": [
            {"url": LANCET, "locator": "Abstract Methods: trial registration NCT02924129, 134 randomized"},
            {"url": JAMA, "locator": "Title, Methods and Figure 1 CONSORT: secondary analysis of Evoke trial, same 134 randomized"},
        ],
        "correction": {"doi": "10.1001/jamaneurol.2022.0022", "url": CORRECTION, "scope": "S780 Figure 4C: closed/open-loop Subthreshold values were switched and corrected online"},
    })
    matrix["rows"].append({
        "batch_id": "ns10-evoke-one-trial-review-2026-09-25",
        "claim": "ECAP-controlled closed-loop SCS was compared with fixed-output open-loop SCS in the Evoke randomized trial.",
        "target_variable": "Patient-reported overall back-and-leg pain response at 3, 12 and 24 months",
        "population_or_data": "NCT02924129; one cohort of 134 randomized chronic back-and-leg-pain patients",
        "source_ids": ["S779", "S780"],
        "verified_evidence": "S779 PubMed abstract gives 3/12-month treatment-arm response and analysis denominators; S780 JAMA full text gives the 24-month follow-up, LOCF primary analysis (67/67) and 50/42 completers for secondary outcomes.",
        "limitations": "The Lancet full method was inaccessible; same trial cannot be double-counted. ECAP is the control signal, not a direct pain observation or a validated patient-level prognostic predictor. S780 Figure 4C had switched Subthreshold values, corrected online.",
        "permitted_conclusion": "Treat as randomized SCS intervention evidence with patient-reported outcomes and a neural feedback mechanism, not as direct ECAP-to-pain prediction evidence.",
        "locators": [
            {"source_id": "S779", "url": LANCET, "locator": "Author abstract, Methods and Findings"},
            {"source_id": "S780", "url": JAMA, "locator": "Methods; Results; Figure 1 and Figure 2"},
            {"source_id": "S780", "url": CORRECTION, "locator": "Error in Figure 4C: closed/open-loop Subthreshold values switched"},
        ],
    })
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    old = "Два DOI пока записаны как лиды протокола и требуют отдельных карточек; статья Lancet доступна здесь лишь на уровне аннотации."
    if todo.count(old) != 1:
        raise ValueError("PA-04 EVOKE TODO note changed")
    todo = todo.replace(old, "Оба DOI оформлены как `S779` и `S780` и объединены как одно испытание NCT02924129 в аудите исходов; статья Lancet доступна здесь лишь на уровне аннотации. NS-10 и PA-04 остаются открытыми до полного snowballing.")
    return protocol, audit, matrix, todo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit, matrix, todo = updated()
    if not args.apply:
        print(f"Dry run: {audit['meta']['records_count']} outcome-audit entries")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns10-evoke-integration")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "scs-outcome-audit.json", audit)
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    print(f"Integrated one EVOKE cohort; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
