"""Index three published NS-03 sources and record source-specific measurement bounds."""

# ruff: noqa: E501 -- preserve exact primary locators and boundaries.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
PLOS = "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0071706"
PNAS = "https://www.pnas.org/doi/10.1073/pnas.1820840116"
CELL = "https://web.archive.org/web/20230522064658/https://www.cell.com/cell/fulltext/S0092-8674(03)00272-1"
IDS = {"S776", "S777", "S778"}
DOIS = {
    "10.1371/journal.pone.0071706": "S776",
    "10.1073/pnas.1820840116": "S777",
    "10.1016/S0092-8674(03)00272-1": "S778",
}


def field(state: str, value: str | None, url: str, locator: str, *, boundary: bool = False) -> dict:
    return {
        "state": state, "value": value,
        "reason": (
            "Conservative inference from source scope; animal defensive behavior does not measure subjective pain."
            if boundary else "Directly checked in the primary article."
        ),
        "checked_at": DATE, "locators": [{"url": url, "locator": locator}],
    }


ENTRIES = [
    {
        "source_id": "S776", "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field("reported", "Third-instar larvae received timed noxious heat, vibration, air current and optogenetic stimuli; wandering-stage animals were used for the nociception assay and foraging-stage animals for the other assays.", PLOS, "Methods, Fly Stocks and Behavior Apparatus; Figure 1"),
            "neural_response": field("reported", "GCaMP3 measured chordotonal-neuron calcium transients to vibration; class IV neurons were silenced or activated in separate behavioral assays. No heat-evoked class IV calcium trace is presented as the behavioral outcome.", PLOS, "Abstract; Methods, GCaMP Imaging; Results, Figure 6C-D and Figure 9"),
            "behavior": field("reported", "Noxious heat induced rolling and escape crawling; class IV neuron inactivation reduced both. Vibration and air current produced different head-casting and crawling actions.", PLOS, "Results, Figures 2, 4 and 6-9"),
            "pain_boundary": field("reported", "Stimulus-linked calcium imaging and larval escape actions are distinct objective measurements; no subjective pain or human SCS response is measured.", PLOS, "Abstract; Results, Figures 2, 4 and 6; Discussion", boundary=True),
        },
    },
    {
        "source_id": "S777", "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field("reported", "Larvae were touched with a 42 C probe or received pr1-cell Chrimson red-light stimulation; developmental pr1 activation was tested at 48-120 h after egg laying.", PNAS, "Results, Figures 1-2 and 4; Materials and Methods"),
            "neural_response": field("not_reported", None, PNAS, "Results, Figures 1A-B and 3D-E: expression imaging and activity-dependent GRASP; no stimulus-evoked firing or calcium response quantified"),
            "behavior": field("reported", "Curling and rolling latency varied with rover/sitter and for-null genotypes; pr1 rescue and knockdown changed thermal responses, and prolonged developmental pr1 activation increased later thermal response latency.", PNAS, "Results, Figures 2C-E and 4B-E"),
            "pain_boundary": field("reported", "Expression and GRASP support a larval circuit hypothesis; rolling latency is a protective action, without direct subjective-pain, connectome-wide or human SCS measurement.", PNAS, "Abstract; Results, Figures 2-4; Discussion", boundary=True),
        },
    },
    {
        "source_id": "S778", "source_role": "primary_experiment",
        "extraction": {
            "stimulus": field("reported", "Drosophila larvae received noxious heated-probe and calibrated mechanical-filament stimuli; the standard thermal assay applied a 46 C probe laterally.", CELL, "Results, Figures 1-2; Experimental Procedures, noxious heat probe"),
            "neural_response": field("reported", "Wild-type larval nerve firing rose above about 38 C; this temperature-linked increase was absent in painless mutant nerve recordings.", CELL, "Results, Figure 3C-E: peripheral nerve electrophysiology"),
            "behavior": field("reported", "Larvae rolled after noxious stimulation; a 45 mN filament elicited rolling in 92% of wild type (n=36) and 13% of painless1 mutants (n=31).", CELL, "Results, Figure 2E: mechanical rolling; Figure 1: thermal rolling"),
            "pain_boundary": field("reported", "Peripheral nerve spikes and protective rolling are different larval outcomes. Neither is subjective pain, a central connectome simulation or validation for human ECAP/SCS.", CELL, "Summary; Results, Figures 1-3; Discussion", boundary=True),
        },
    },
]


def updated() -> tuple[dict, dict, dict, str]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    canonical = {r["id"]: r for r in records["sources"]}
    if not IDS <= set(canonical):
        raise ValueError("Publish canonical cards first")
    if any(canonical[source_id]["identifiers"]["doi"].lower() != doi.lower() for doi, source_id in DOIS.items()):
        raise ValueError("Canonical DOI changed")
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    stream = next(s for s in protocol["search_streams"] if s["id"] == "NS-03")
    if {lead["doi"].lower() for lead in stream["unindexed_primary_leads"]} != {d.lower() for d in DOIS}:
        raise ValueError("Pending primary leads changed")
    if IDS & {e["source_id"] for e in audit["entries"]}:
        raise ValueError("Sources already audited")
    indexed = []
    for lead in stream["unindexed_primary_leads"]:
        entry = {**lead, "source_id": DOIS[lead["doi"]], "status": "primary_full_text_canonical_card_and_audit_recorded"}
        if entry["source_id"] == "S778":
            entry["url"] = CELL
            entry["locator"] = "Archived Cell publisher full text, Results Figures 1-3 and Experimental Procedures"
        indexed.append(entry)
    stream["source_ids"] = sorted([*stream["source_ids"], *IDS])
    stream["unindexed_primary_leads"] = []
    stream["indexed_primary_leads"].extend(indexed)
    stream["coverage_note"] = "Twenty-one canonical candidates have source-specific stimulus, neural-response, behavior and pain-boundary extraction. S776 distinguishes heat behavior from vibration calcium imaging; S777 has expression/GRASP evidence without a measured stimulus-evoked neural response; S778 gives peripheral nerve firing and rolling. Backward and forward citation screening remains open; no subjective-pain or human SCS inference follows."
    audit["meta"].update({
        "generated_at": DATE, "records_count": len(audit["entries"]) + len(ENTRIES),
        "candidate_source_ids": stream["source_ids"], "unindexed_primary_leads": [],
    })
    audit["meta"]["indexed_primary_leads"].extend(indexed)
    audit["entries"].extend(ENTRIES)
    audit["entries"].sort(key=lambda e: e["source_id"])
    matrix["rows"].append({
        "batch_id": "ns03-backward-primary-2026-09-25",
        "claim": "Larval sensory and peripheral neural mechanisms produce stimulus-dependent defensive behavior.",
        "target_variable": "Noxious-stimulus rolling/escape and peripheral neural or anatomical evidence",
        "population_or_data": "Drosophila melanogaster larvae; assay-specific animal groups",
        "source_ids": ["S776", "S777", "S778"],
        "verified_evidence": "S776 pairs heat-related behavior with separate vibration calcium imaging; S777 tests pr1/for in rolling and GRASP without a heat-evoked neural trace; S778 pairs peripheral nerve firing with thermal and mechanical behavioral assays.",
        "limitations": "None measures subjective pain, human ECAP/SCS outcomes or validated cross-species transfer; S778 full text was read from an archived publisher page because live access was blocked.",
        "permitted_conclusion": "Use as larval nociception and defensive-behavior prior art with distinct assay scopes.",
        "locators": [
            {"source_id": "S776", "url": PLOS, "locator": "Results, Figures 2, 4 and 6; Methods"},
            {"source_id": "S777", "url": PNAS, "locator": "Results, Figures 2-4; Methods"},
            {"source_id": "S778", "url": CELL, "locator": "Results, Figures 1-3; Experimental Procedures"},
        ],
    })
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    old = "  По цитированиям `S212`/`S282` обнаружены три ещё не оформленных первичных источника: Ohyama 2013, Dason 2019 и Tracey 2003. Они занесены как лиды NS-03 с границами вывода; полный метод Tracey и карточки всех трёх требуют отдельной проверки. Пункт остаётся открытым."
    if todo.count(old) != 1:
        raise ValueError("SRC-04 TODO lead note changed")
    todo = todo.replace(old, "  Дополнение 25.09: `S776`–`S778` введены из обратных ссылок `S212`/`S282` и по первичным текстам раздельно занесены в NS-03. `S777` не содержит прямой записи вызванной нейронной активности; `S778` проверен по архиву издательской страницы. Поиск цитирований ещё открыт, как и зависимость `SRC-03`.")
    todo = todo.replace("NS-03 содержит 18 канонических кандидатов", "NS-03 содержит 21 канонического кандидата")
    todo = todo.replace("для всех 18 `data/drosophila-nociception-audit.json`", "для всех 21 `data/drosophila-nociception-audit.json`")
    return protocol, audit, matrix, todo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit, matrix, todo = updated()
    if not args.apply:
        print(f"Dry run: {audit['meta']['records_count']} NS-03 entries")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns03-backward-primary-integration")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "drosophila-nociception-audit.json", audit)
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    print(f"Integrated NS-03 sources; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
