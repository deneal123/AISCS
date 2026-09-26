"""Integrate five staged primary analogues into PA-04 traceability."""

# ruff: noqa: E501 -- source boundaries and exact locators are kept readable.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
BATCH_SHA256 = "D9D2D0F23251B9DADB4D13BFE5FEA78D7C1CDBFD713A3A56A3EC67A9407009E3"
SOURCES = {
    "S784": ("NS-09", "https://pubmed.ncbi.nlm.nih.gov/22188868/", "Abstract, Results: A-beta recruitment and painful-area coverage", "Human ECAP recruitment and painful-area coverage; pain-intensity response is not measured by ECAP."),
    "S785": ("NS-07", "https://pubmed.ncbi.nlm.nih.gov/24111244/", "Abstract: hybrid three-dimensional electrical and neural forward model", "Simulated ECAP forward model; no independent patient validation established in the accessible abstract."),
    "S786": ("NS-08", "https://pubmed.ncbi.nlm.nih.gov/30273153/", "Abstract: electrode double-layer mechanism and saline comparison", "Bench electrode pulse artifact model; not human SCS artifact-removal validation."),
    "S787": ("NS-09", "https://pmc.ncbi.nlm.nih.gov/articles/PMC8320888/", "Methods, ECAP acquisition and growth curves; Results, ET-PT and ET-DT", "14 participants and 112 repeated curves; perception/discomfort thresholds, not pain relief."),
    "S788": ("NS-10", "https://pubmed.ncbi.nlm.nih.gov/28922517/", "Abstract, Materials and Methods and Results: 51 trialed, 36 implanted, six-month outcomes", "AVALON preliminary single-arm outcomes; no randomized comparator or prognostic ECAP model."),
}


def extraction(value: str | None, url: str, locator: str, *, state: str = "reported") -> dict:
    return {
        "state": state, "value": value,
        "reason": "Primary abstract or full text at the named locator; access and design limits retained.",
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    ecap = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    outcome = json.loads((DATA / "scs-outcome-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    cards = {r["id"]: r for r in records["sources"]}
    assert all(sid in cards for sid in SOURCES)
    assert not any(row["batch_id"].startswith("pa04-five-analogue") for row in matrix["rows"])
    assert not any(e["source_id"] in SOURCES for e in ecap["entries"] + outcome["entries"])
    streams = {s["id"]: s for s in protocol["search_streams"]}
    for sid, (stream_id, url, locator, boundary) in SOURCES.items():
        stream = streams[stream_id]
        assert sid not in stream["source_ids"]
        stream["source_ids"].append(sid)
        stream["source_ids"].sort()
        stream.setdefault("indexed_primary_leads", []).append({
            "doi": cards[sid]["identifiers"]["doi"], "source_id": sid,
            "title": cards[sid]["название"], "url": url, "locator": locator,
            "status": "primary_card_and_pa04_audit_recorded", "boundary": boundary,
        })
        matrix["rows"].append({
            "batch_id": f"pa04-five-analogue-{sid.lower()}-2026-09-25",
            "claim": cards[sid]["название"],
            "target_variable": cards[sid]["evidence"]["target_label"],
            "population_or_data": cards[sid]["evidence"]["population"],
            "source_ids": [sid], "verified_evidence": cards[sid]["производительность"],
            "limitations": cards[sid]["ограничения"],
            "permitted_conclusion": boundary,
            "locators": [{"source_id": sid, "url": url, "locator": locator}],
        })
        if sid != "S788":
            ecap["entries"].append({"source_id": sid, "extraction": {
                "sample": extraction(cards[sid]["датасет"], url, locator),
                "electrode_geometry": extraction(None, url, locator, state="not_reported"),
                "stimulation": extraction(cards[sid]["метод"], url, locator),
                "split_unit": extraction(None, url, locator, state="not_applicable"),
                "metrics": extraction(cards[sid]["производительность"], url, locator),
            }})
        else:
            outcome["entries"].append({"source_id": sid, "extraction": {
                "input_role": extraction("ECAP feedback controls SCS stimulation; not a direct pain measurement or baseline prognostic predictor.", url, locator),
                "target_role": extraction("Patient-reported pain and function over three and six months after implant.", url, locator),
                "study_design": extraction("AVALON prospective open-label single-arm preliminary cohort; 51 trialed and 36 permanently implanted.", url, locator),
                "prognostic_validation": extraction(None, url, locator, state="not_applicable"),
            }})
    # The FDA primary review and institutional metadata identify ACTRN12615000713594
    # as AVALON. The public NCT02161627 record identifies Panorama instead.
    fda = "https://www.accessdata.fda.gov/cdrh_docs/pdf19/P190002B.pdf"
    anzca = "https://airr.anzca.edu.au/anzcacrisjspui/handle/11055/573?mode=full"
    panorama = "https://clinicaltrials.gov/api/v2/studies/NCT02161627"
    outcome["study_families"].append({
        "trial_id": "ACTRN12615000713594", "source_ids": ["S788"],
        "decision": "AVALON preliminary prospective single-arm cohort, distinct from EVOKE NCT02924129 and Panorama NCT02161627. Do not count as a randomized comparator or independent outcome-prediction validation.",
        "locators": [
            {"url": anzca, "locator": "Institutional author record: trial registration ACTRN12615000713594"},
            {"url": fda, "locator": "Avalon study design and clinical evidence summary"},
            {"url": panorama, "locator": "Protocol acronym Panorama and randomized crossover design"},
        ],
    })
    s788 = cards["S788"]
    s788["ограничения"] += " Correct AVALON registration: ACTRN12615000713594 (FDA SSED; ANZCA author record)."
    s788["validation"]["notes"] = s788["ограничения"]
    for key in ("ограничения", "validation.notes"):
        s788["field_resolution"][key]["value"] = s788["ограничения"]
        s788["field_resolution"][key]["reason"] = "Official FDA review and author institutional record identify AVALON registration; ClinicalTrials.gov identifies Panorama separately."
        s788["field_resolution"][key]["locators"] = [
            {"url": anzca, "locator": "Registration ACTRN12615000713594"},
            {"url": fda, "locator": "AVALON study overview"},
            {"url": panorama, "locator": "Panorama acronym and crossover design"},
        ]
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-10", "date": DATE,
        "queries": ["PA-04 backward primary citation screen: Parker 2012, Laird 2013, Single 2018, Pilitsis 2021, Russo 2018", "AVALON ACTRN12615000713594 versus Panorama NCT02161627"],
        "primary_urls": [v[1] for v in SOURCES.values()] + [fda, anzca, panorama],
        "new_mechanism_classes": [], "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    ecap["entries"].sort(key=lambda e: e["source_id"])
    outcome["entries"].sort(key=lambda e: e["source_id"])
    for audit in (ecap, outcome):
        audit["meta"].update({"generated_at": DATE, "records_count": len(audit["entries"])})
    matrix["meta"]["generated_at"] = DATE
    needle = "- [ ] **PA-05.**"
    assert todo.count(needle) == 1
    todo = todo.replace(needle, "  Дополнение 25.09: пять первичных аналогов `S784`–`S788` опубликованы через stage/publish (SHA-256 пакета `" + BATCH_SHA256 + "`) и внесены в NS-07–NS-10, аудиты и матрицу. `S784` и `S787` измеряют ECAP/порог восприятия, а не обезболивание; `S785` — модель, `S786` — стендовый артефакт. `S788` — одногрупповая AVALON (ACTRN12615000713594), не рандомизированная Panorama (NCT02161627). Snowballing и более позднее датированное обновление остаются открытыми; PA-04 не закрыт.\n" + needle)
    readme = readme.replace("- `archive/`", "- `pa04-five-primary-analogue-audit-2026-09-25.json` — primary locators, batch SHA-256 and AVALON/Panorama identity correction;\n- `archive/`")
    audit_note = {"date": DATE, "batch_sha256": BATCH_SHA256, "source_ids": list(SOURCES), "source_locators": [{"source_id": sid, "stream": v[0], "url": v[1], "locator": v[2], "boundary": v[3]} for sid, v in SOURCES.items()], "registration_correction": {"avalon": "ACTRN12615000713594", "panorama": "NCT02161627", "locators": [anzca, fda, panorama]}, "remaining": "Complete citation snowballing and later dated refresh before PA-04 closure."}
    if not args.apply:
        print(f"Dry run: {len(SOURCES)} sources; {len(ecap['entries'])} ECAP and {len(outcome['entries'])} outcome entries")
        return
    snapshot = snapshot_repository(DATA, label="pre-pa04-five-analogue-integration")
    for name, obj in (("records.json", records), ("search-protocol.json", protocol), ("ecap-scs-audit.json", ecap), ("scs-outcome-audit.json", outcome), ("evidence-matrix.json", matrix), ("pa04-five-primary-analogue-audit-2026-09-25.json", audit_note)):
        atomic_write_json(DATA / name, obj)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Integrated five PA-04 sources; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
