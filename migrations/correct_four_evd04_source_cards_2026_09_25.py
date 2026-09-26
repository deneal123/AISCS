"""Align four source-card targets with the primary outcomes and evidence matrix."""

# ruff: noqa: E501 -- primary locators and scientific boundary text are intentional.

import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
URLS = {
    "S023": "https://eprints.gla.ac.uk/345351/",
    "S149": "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full",
    "S154": "https://www.mdpi.com/2306-5729/10/2/11",
    "S273": "https://advanced.onlinelibrary.wiley.com/doi/abs/10.1002/adsu.70449",
}


def set_field(source: dict, path: str, old: object, new: object, reason: str, locator: str) -> dict:
    group, name = path.split(".", 1)
    assert source[group][name] == old, (source["id"], path, source[group][name])
    source[group][name] = new
    resolution = source["field_resolution"][path]
    resolution.update(
        state="reported" if new is not None else "not_reported",
        value=new,
        reason=reason,
        checked_at=DATE,
        locators=[{"url": URLS[source["id"]], "locator": locator}],
    )
    return {"field": path, "old": old, "new": new, "locator": locator}


def main() -> None:
    records_path = DATA / "records.json"
    vocab_path = DATA / "vocabularies.json"
    completeness_path = DATA / "completeness-report.json"
    todo_path = ROOT / "TODO.md"
    readme_path = DATA / "README.md"
    records = json.loads(records_path.read_text(encoding="utf-8"))
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    completeness = json.loads(completeness_path.read_text(encoding="utf-8"))
    sources = {source["id"]: source for source in records["sources"]}
    changes: dict[str, list[dict]] = {id_: [] for id_ in URLS}

    for value in ("future_neuropathic_pain_onset", "nociceptor_translatomic_response", "mixed_pain_benchmark_labels"):
        assert value not in vocab["target_construct"]
        vocab["target_construct"].append(value)

    def change(id_: str, path: str, old: object, new: object, reason: str, locator: str) -> None:
        changes[id_].append(set_field(sources[id_], path, old, new, reason, locator))

    change("S023", "evidence.target_construct", "clinical_function", "future_neuropathic_pain_onset", "The endpoint is future central neuropathic-pain development, not functional status.", "Abstract, Methods: PDP versus PNP within six months after subacute SCI")
    change("S023", "evidence.target_label", None, "PDP versus PNP within six months after subacute spinal cord injury", "Two independent patient datasets classify later central neuropathic-pain onset.", "Abstract, Methods: datasets A (N=20) and B (N=35)")
    change("S023", "evidence.species", None, "Homo sapiens", "The primary article describes human participants with subacute spinal cord injury.", "Abstract, Methods: participants with subacute spinal cord injury")
    change("S023", "evidence.population", None, "Participants with subacute spinal cord injury without neuropathic pain at EEG recording", "PDP and PNP are defined by pain development within six months.", "Abstract, Methods: cohort eligibility and six-month follow-up")
    change("S023", "evidence.sample_size", None, "Dataset A N=20; dataset B N=35", "The published abstract gives separate dataset sizes.", "Abstract, Methods: datasets A and B")
    change("S023", "evidence.subject_domain", "unavailable_after_search", "human_clinical", "Participants had subacute spinal cord injury.", "Abstract, Methods: participant population")
    change("S023", "evidence.access_status", "unavailable_after_search", "open", "The university repository provides the published full-text PDF.", "Text > 345351.pdf, Published Version")

    change("S149", "evidence.target_construct", "experimental_pain_class", "mixed_pain_benchmark_labels", "The three datasets use different targets and cannot share one experimental-pain class.", "Section 4.1 Benchmark datasets; Section 4.3 neonatal cohort")
    change("S149", "evidence.target_label", "continuous 0-10 pain intensity / dataset-specific pain labels", "UNBC PSPI facial-action score (0-16 converted to 0-10); BioVid four heat-intensity classes; neonatal binary pain/no-pain, with separate N-PASS subset regression", "UNBC PSPI is an observer-derived facial-action score, not patient self-report; BioVid and neonatal labels are distinct.", "Sections 4.1 and 4.3; Tables 9-11")

    change("S154", "evidence.target_construct", "nociceptive_response", "nociceptor_translatomic_response", "The dataset measures ribosome-bound RNA abundance rather than evoked neural activity or behavior.", "Abstract; Section 2.1 Data Description: TRAP RNA-seq after UV versus sham")
    change("S154", "evidence.target_label", None, "Larval nociceptor ribosome-bound RNA abundance 24 h after UV versus sham injury", "The reported readout is nociceptor-specific translatomic RNA sequencing.", "Abstract; Section 2.1 Data Description")
    change("S154", "evidence.population", None, "Third-instar Drosophila larvae", "The preparation is third-instar larvae.", "Abstract; Section 2.1 Data Description")
    change("S154", "evidence.access_status", "unavailable_after_search", "open", "The publisher provides the full open article.", "Publisher article, Abstract and Sections 1-2")

    change("S273", "evidence.target_construct", "nociceptive_response", "protective_behavior", "Hot-plate paw withdrawal is a mouse behavioral endpoint, not a neural recording.", "Abstract: mouse hot-plate paw-withdrawal latency")
    change("S273", "evidence.target_label", None, "Female mouse hot-plate paw-withdrawal latency after TENS-equivalent stimulation", "The abstract reports a change from 7.3 +/- 0.2 s to about 10.7 s; no human dysmenorrhea outcome is measured.", "Abstract: female-mouse proof-of-concept and paw-withdrawal latency")
    change("S273", "evidence.species", None, "Mus musculus", "The primary abstract specifies female mice.", "Abstract: female mice in hot-plate model")
    change("S273", "evidence.population", None, "Female mice in a hot-plate proof-of-concept experiment", "The abstract does not report the mouse sample size.", "Abstract: female-mouse proof-of-concept")
    change("S273", "evidence.subject_domain", "unavailable_after_search", "animal_other", "The measured proof-of-concept endpoint is from mice.", "Abstract: female-mouse hot-plate model")

    todo = todo_path.read_text(encoding="utf-8")
    anchor = "  Черновой реестр `data/forbidden-transfer-audit-2026-09-25.json`"
    assert todo.count(anchor) == 1
    note = "  Дополнение 25.09: карточки `S023`, `S149`, `S154`, `S273` приведены к разным первичным целевым исходам; `S023` и `S154` получили подтверждённый доступ к полным текстам. У `S273` проверена только издательская аннотация и размер группы мышей не указан. См. `data/four-source-card-construct-corrections-2026-09-25.json`; `EVD-04` остаётся открытым до просмотра остальных карточек и зависимости `EVD-03`.\n"
    assert note not in todo
    todo = todo.replace(anchor, note + anchor, 1)
    readme = readme_path.read_text(encoding="utf-8")
    entry = "- `four-source-card-construct-corrections-2026-09-25.json` — primary-locator corrections of four source-card target constructs and labels;\n"
    assert entry not in readme
    assert readme.count("- `archive/`") == 1
    readme = readme.replace("- `archive/`", entry + "- `archive/`", 1)

    snapshot = snapshot_repository(DATA, label="pre-four-source-card-construct-corrections")
    completeness.update(completeness_summary(records["sources"]))
    atomic_write_json(records_path, records)
    atomic_write_json(vocab_path, vocab)
    atomic_write_json(completeness_path, completeness)
    audit = {
        "meta": {"checked_at": DATE, "gate": "G0_REVISE", "snapshot": str(snapshot)},
        "primary_locators": URLS,
        "changes": changes,
        "boundary": "Card and matrix targets are aligned for these four sources only; full source-card review and EVD-03 dependency remain open.",
    }
    atomic_write_json(DATA / "four-source-card-construct-corrections-2026-09-25.json", audit)
    todo_path.write_text(todo, encoding="utf-8")
    readme_path.write_text(readme, encoding="utf-8")
    print(f"Corrected four source cards; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
