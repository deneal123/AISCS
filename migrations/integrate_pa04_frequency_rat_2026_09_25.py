"""Trace two newly published PA-04 analogues through search and evidence audits."""

# ruff: noqa: E501 -- exact study boundaries and locators are kept readable.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
SOURCES = {
    "S789": {
        "stream": "NS-09",
        "sha256": "6853B50AFA6C32DE78168D4B6A0E95583F965B6DBF19F2666878D64D2336D1C1",
        "url": "https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2021.625835/full",
        "locator": "Methods > Patient Recruitment and Frequency Sweeps; Results > Figs 3-4; Discussion",
        "boundary": "Human ECAP amplitude and separately rated stimulation-induced paresthesia diverge with frequency; neither is a measured analgesia endpoint. Repeated sweeps are not independent patients.",
    },
    "S790": {
        "stream": "NS-10",
        "sha256": "DC43DB52760D4608B06D376BB9F5872B5FC81C9B29779C25A10BDD442965EA52",
        "url": "https://link.springer.com/article/10.1186/s42234-023-00134-1",
        "locator": "Methods > Animals, Experimental design and Pain hypersensitivity assessment; Results > Fig. 8",
        "boundary": "ECAP-controlled SCS reduced rat SNI mechanical/cold hypersensitivity in paw-withdrawal assays; no patient pain or human clinical response was measured. SCS-ON/OFF assignment was not randomized and the tester was not blinded.",
    },
}


def extracted(value: object, info: dict, *, state: str = "reported") -> dict:
    return {
        "state": state,
        "value": value,
        "reason": "Primary full text at the named locator; cohort and construct limits retained.",
        "checked_at": DATE,
        "locators": [{"url": info["url"], "locator": info["locator"]}],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    ecap = json.loads((DATA / "ecap-scs-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    cards = {source["id"]: source for source in records["sources"]}
    streams = {stream["id"]: stream for stream in protocol["search_streams"]}
    assert all(sid in cards for sid in SOURCES)
    assert not any(row["batch_id"].startswith("pa04-frequency-rat-") for row in matrix["rows"])
    assert not any(entry["source_id"] in SOURCES for entry in ecap["entries"])
    assert "NS-RUN-2026-09-25-11" not in {run["id"] for run in protocol["search_runs"]}

    for sid, info in SOURCES.items():
        card = cards[sid]
        stream = streams[info["stream"]]
        assert sid not in stream["source_ids"]
        stream["source_ids"].append(sid)
        stream["source_ids"].sort()
        stream.setdefault("indexed_primary_leads", []).append({
            "doi": card["identifiers"]["doi"], "source_id": sid,
            "title": card["название"], "url": info["url"],
            "locator": info["locator"], "status": "primary_card_and_pa04_audit_recorded",
            "boundary": info["boundary"],
        })
        matrix["rows"].append({
            "batch_id": f"pa04-frequency-rat-{sid.lower()}-2026-09-25",
            "claim": card["название"],
            "target_variable": card["evidence"]["target_label"],
            "population_or_data": card["evidence"]["population"],
            "source_ids": [sid],
            "verified_evidence": card["производительность"],
            "limitations": card["ограничения"],
            "permitted_conclusion": info["boundary"],
            "locators": [{"source_id": sid, "url": info["url"], "locator": info["locator"]}],
        })
        ecap["entries"].append({"source_id": sid, "extraction": {
            "sample": extracted(card["датасет"], info),
            "electrode_geometry": extracted("Six-contact epidural lead" if sid == "S790" else None, info, state="reported" if sid == "S790" else "not_reported"),
            "stimulation": extracted(card["метод"], info),
            "split_unit": extracted(None, info, state="not_applicable"),
            "metrics": extracted(card["производительность"], info),
        }})
    ecap["entries"].sort(key=lambda entry: entry["source_id"])
    ecap["meta"].update(generated_at=DATE, records_count=len(ecap["entries"]))
    matrix["meta"]["generated_at"] = DATE
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-11", "date": DATE,
        "queries": ["PA-04 bounded backward citation screen from S787 and related ECAP primary articles; Gmel frequency and Versantvoort rat SNI"],
        "primary_urls": [info["url"] for info in SOURCES.values()],
        "new_mechanism_classes": [], "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    note = "  Дополнение 25.09: `S789` (человеческие ECAP и ощущение парестезии при частотных sweep, без исхода обезболивания) и `S790` (ECAP-controlled SCS на крысах SNI с von Frey/acetone withdrawal) опубликованы после stage и проверены по первичным методам. У `S790` назначение SCS-ON/OFF не рандомизировано, тестирующий не ослеплён; разные виды и исходы не объединены. `data/pa04-frequency-rat-citation-audit-2026-09-25.json` хранит SHA-256 staging. Дальнейший snowballing и позднейшее датированное обновление открыты; `PA-04` не закрыт.\n"
    anchor = "- [ ] **PA-05.**"
    assert todo.count(anchor) == 1 and note not in todo
    todo = todo.replace(anchor, note + anchor, 1)
    entry = "- `pa04-frequency-rat-citation-audit-2026-09-25.json` — primary ECAP-frequency and rat SNI analogues with staging SHA-256 and construct boundaries;\n"
    assert entry not in readme
    assert readme.count("- `archive/`") == 1
    readme = readme.replace("- `archive/`", entry + "- `archive/`", 1)
    audit = {
        "date": DATE, "gate": "G0_REVISE", "source_ids": list(SOURCES),
        "staging_sha256": {sid: info["sha256"] for sid, info in SOURCES.items()},
        "primary_locators": [{"source_id": sid, "url": info["url"], "locator": info["locator"], "boundary": info["boundary"]} for sid, info in SOURCES.items()],
        "cohort_overlap": {"source_id": "S789", "related_doi": "10.3389/fnins.2023.1297814", "status": "same recruited 20-patient study setup; distinct analysis, not an independent cohort", "url": "https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2023.1297814/full", "locator": "Introduction, final paragraph; Methods 2.1; Results 3.1"},
        "pending_leads": ["10.3389/fnins.2023.1297814", "10.1136/rapm-2026-107607"],
        "remaining": "Complete forward/backward citation screening and a later dated refresh before PA-04 closure.",
    }
    if not args.apply:
        print(f"Dry run: {len(SOURCES)} sources, {len(ecap['entries'])} ECAP audit entries, {len(matrix['rows'])} matrix rows")
        return
    snapshot = snapshot_repository(DATA, label="pre-pa04-frequency-rat-integration")
    for name, obj in (("search-protocol.json", protocol), ("ecap-scs-audit.json", ecap), ("evidence-matrix.json", matrix), ("pa04-frequency-rat-citation-audit-2026-09-25.json", audit)):
        atomic_write_json(DATA / name, obj)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Integrated S789/S790; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
