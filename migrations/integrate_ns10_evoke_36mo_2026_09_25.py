"""Link the 36-month EVOKE report to its trial family and access audit."""

# ruff: noqa: E501 -- source-specific follow-up and access boundaries matter.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC11103285/"


def field(state: str, value: str | None, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": state, "value": value,
        "reason": "Randomized treatment effect, not a validated prospective prognostic prediction model." if boundary else "Checked in the deposited primary full text.",
        "checked_at": DATE, "locators": [{"url": URL, "locator": locator}],
    }


ENTRY = {
    "source_id": "S781",
    "extraction": {
        "input_role": field("reported", "ECAP is the feedback signal controlling stimulation current in the closed-loop therapy arm; both arms used the same device and ECAP-guided programming. It is not a direct pain measure or a baseline prognostic predictor.", "Methods, Intervention; Results, Neural activation; Discussion, Strengths and limitations", boundary=True),
        "target_role": field("reported", "At least 50% or 80% reduction in patient-reported overall back-and-leg pain at 36 months; holistic response is a separate multidomain outcome.", "Abstract, Methods and Results; Figure 3; Table 1"),
        "study_design": field("reported", "36-month, non-prespecified follow-up of the same NCT02924129 randomized cohort as S779/S780. All 134 randomized patients (67/67) entered intention-to-treat pain analysis with last-value-carried-forward; 113 were implanted.", "Methods, Statistical analysis; Results, Summary of participation and crossover; Figure 2 CONSORT"),
        "prognostic_validation": field("not_applicable", None, "Methods: intervention-arm comparison, no preimplant outcome-prediction model", boundary=True),
    },
}


def updated() -> tuple[dict, dict, dict, dict, str]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(r for r in records["sources"] if r["id"] == "S781")
    if source["identifiers"]["doi"] != "10.1136/rapm-2023-104751":
        raise ValueError("S781 identity changed")
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "scs-outcome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    access = json.loads((DATA / "human-ecap-scs-access-audit.json").read_text(encoding="utf-8"))
    stream = next(s for s in protocol["search_streams"] if s["id"] == "NS-10")
    if "S781" in stream["source_ids"] or any(e["source_id"] == "S781" for e in audit["entries"]):
        raise ValueError("S781 already integrated")
    stream["source_ids"].append("S781")
    stream["source_ids"].sort()
    stream["indexed_primary_leads"].append({
        "doi": "10.1136/rapm-2023-104751", "source_id": "S781",
        "title": source["название"], "url": URL,
        "locator": "Methods, Statistical analysis; Results, Figure 2 and Figure 3; Discussion, Strengths and limitations",
        "status": "primary_full_text_canonical_card_and_outcome_audit_recorded",
        "boundary": "Same NCT02924129 cohort; non-prespecified 36-month follow-up, not independent trial or prognostic model.",
    })
    stream["coverage_note"] = stream["coverage_note"].replace("EVOKE 3/12-month Lancet (S779) and 24-month JAMA (S780) reports", "EVOKE 3/12-month Lancet (S779), 24-month JAMA (S780) and 36-month RAPM (S781) reports").replace("and its Figure 4 has a correction.", "and its Figure 4C has a correction. The 36-month analysis was not prespecified and used LOCF.")
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-05", "date": DATE,
        "queries": ["EVOKE NCT02924129 36-month primary report DOI 10.1136/rapm-2023-104751", "PMID 37640452 full text and duplicate screen"],
        "primary_urls": [URL, "https://pubmed.ncbi.nlm.nih.gov/37640452/"],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    audit["entries"].append(ENTRY)
    audit["entries"].sort(key=lambda e: e["source_id"])
    audit["meta"].update({"generated_at": DATE, "records_count": len(audit["entries"])})
    family = next(f for f in audit["study_families"] if f["trial_id"] == "NCT02924129")
    family["source_ids"].append("S781")
    family["decision"] = "One randomized cohort with 3/12-, 24- and 36-month reports; count as one trial, not three independent validations. The 36-month analysis was not prespecified."
    family["locators"].append({"url": URL, "locator": "Abstract trial registration; Introduction references 11-12; Methods, Statistical analysis"})
    row = next(r for r in matrix["rows"] if r["batch_id"] == "ns10-evoke-one-trial-review-2026-09-25")
    row["source_ids"].append("S781")
    row["target_variable"] = "Patient-reported overall back-and-leg pain response at 3, 12, 24 and 36 months"
    row["verified_evidence"] += " S781 full text adds the non-prespecified 36-month analysis with LOCF for all 134 randomized patients."
    row["limitations"] += " S781 is the same cohort and cannot be counted as replication; both arms received ECAP-guided programming."
    row["locators"].append({"source_id": "S781", "url": URL, "locator": "Methods, Statistical analysis; Results, Figures 2-3; Discussion, Strengths and limitations"})
    candidate = next(c for c in access["candidates"] if c["id"] == "HES-EVOKE-NCT02924129")
    candidate["source_refs"] = ["S779", "S780", "S781"]
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    old = "Оба DOI оформлены как `S779` и `S780` и объединены как одно испытание NCT02924129 в аудите исходов; статья Lancet доступна здесь лишь на уровне аннотации. NS-10 и PA-04 остаются открытыми до полного snowballing."
    if todo.count(old) != 1:
        raise ValueError("PA-04 EVOKE note changed")
    todo = todo.replace(old, "Три отчёта EVOKE оформлены как `S779`–`S781` и объединены как одно испытание NCT02924129 в аудите исходов; статья Lancet доступна здесь лишь на уровне аннотации. 36-месячный анализ `S781` не был заранее задан и использует перенос последнего значения для пропусков. NS-10 и PA-04 остаются открытыми до полного snowballing.")
    return protocol, audit, matrix, access, todo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit, matrix, access, todo = updated()
    if not args.apply:
        print(f"Dry run: {audit['meta']['records_count']} outcome-audit entries")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns10-evoke-36mo-integration")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "scs-outcome-audit.json", audit)
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "human-ecap-scs-access-audit.json", access)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    print(f"Integrated S781 in EVOKE cohort; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
