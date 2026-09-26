"""Correct three imported 2026 owner-page cards against their live text."""

# ruff: noqa: E501 -- scientific boundaries and primary locators remain explicit.

import argparse
import json
from collections import Counter
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
SPECS = {
    "S253": {
        "url": "https://eon.systems/updates/embodied-brain-emulation",
        "locator": "Research, March 10 2026; How does the fly work?; What the current embodied fly is not; Is this an upload?",
        "values": {
            "модальность": "Connectome-constrained simulated fly embodiment",
            "задача": "Describe a virtual adult-fly brain-body integration and its limits",
            "метод": "Company technical account of a Shiu et al. LIF brain model integrated with NeuroMechFly v2/MuJoCo via selected descending-neuron outputs and hand-chosen mappings",
            "датасет": "Published adult-fly connectome and simulated body components; no new patient or biological validation dataset in this post",
            "ограничения": "Owner technical post, not a peer-reviewed experiment. Behaviors rely on existing body controllers and hand-chosen mappings; authors explicitly report no validation of internal dynamics against biological signatures. No nociception or pain endpoint.",
            "evidence.species": "Drosophila melanogaster (simulated adult fly)",
            "evidence.population": "Virtual adult-fly model; no experimental animal cohort in this post",
            "evidence.subject_domain": "simulation",
            "evidence.modalities": ["connectome", "simulation_state"],
            "evidence.target_construct": "not_applicable",
            "evidence.target_label": "Simulated grooming, feeding and foraging behavior, without nociceptive endpoint",
            "evidence.access_status": "open",
            "validation.notes": "Eon owner technical article describes integration of published fly-brain and body models, sparse descending control, and hand-chosen mappings. It explicitly says internal dynamics have not been validated against biological signatures. This is not independent empirical behavioral, nociceptive or pain validation.",
        },
        "boundary": "Owner technical description of one fly embodiment demo; not independent experimental validation.",
    },
    "S296": {
        "url": "https://eon.systems/updates/first-multi-behavior-brain-upload",
        "locator": "Announcement, March 7 2026, paragraphs 1-6: fly demo and future mouse target",
        "values": {
            "модальность": "Company announcement of simulated fly embodiment",
            "задача": "Announce a fly brain-body demonstration and future mouse-emulation programme",
            "метод": "Video and owner description of an integration of existing adult-fly connectome model with a simulated fly body; no new peer-reviewed method reported",
            "датасет": "Existing adult-fly connectome model; mouse-brain emulation is a future target, not a released dataset",
            "ограничения": "Company announcement of the same fly demonstration elaborated in S253; no completed mouse connectome or emulation, independent biological validation, nociception or pain endpoint.",
            "evidence.species": "Drosophila melanogaster (simulated adult fly)",
            "evidence.population": "Virtual fly demonstration; mouse work described as a future goal",
            "evidence.subject_domain": "simulation",
            "evidence.modalities": ["connectome", "simulation_state"],
            "evidence.target_construct": "not_applicable",
            "evidence.target_label": "Simulated fly behaviors in a company demonstration; future mouse goal is not data",
            "evidence.access_status": "open",
            "validation.notes": "Eon owner announcement on March 7 2026 describes the same fly embodiment demonstration as the March 10 technical article S253 and calls mouse emulation a future mission. Do not count the posts as independent validation or as a released mouse dataset.",
        },
        "boundary": "Same Eon demonstration as S253; mouse programme remains future work.",
    },
    "S368": {
        "url": "https://blog.google/innovation-and-ai/technology/research/male-fruit-fly-brain-map/",
        "locator": "Google Research article, posted September 3 and updated September 21 2026; introduction and five visuals",
        "values": {
            "модальность": "Adult male Drosophila connectome anatomy",
            "задача": "Communicate a mapped adult male fly brain and ventral nerve cord and companion anatomical studies",
            "метод": "Institutional visual explanation of electron-microscopy connectome reconstruction; no dynamic connectome simulation is reported",
            "датасет": "Adult male Drosophila brain and ventral-nerve-cord map with more than 166,000 neurons; immutable graph release is not specified on this page",
            "ограничения": "Institutional communications article, not the underlying methods paper or graph release. It does not report simulation, pain or nociception validation; companion studies must be evaluated separately.",
            "evidence.species": "Drosophila melanogaster (adult male)",
            "evidence.population": "Adult male fly brain and ventral-nerve-cord anatomical map",
            "evidence.subject_domain": "drosophila_adult",
            "evidence.modalities": ["connectome"],
            "evidence.target_construct": "not_applicable",
            "evidence.target_label": "Anatomical connectivity map, not simulated neural activity",
            "evidence.access_status": "open",
            "validation.notes": "Google Research owner article was updated September 21 2026 and describes an adult male fly brain/VNC map with more than 166,000 neurons. It links companion studies but itself reports no dynamic simulation, pain model or immutable connectome release.",
        },
        "boundary": "Anatomical map and communications article only; no dynamic simulation or clinical/pain endpoint.",
    },
}


def update_card(card: dict, spec: dict) -> None:
    locator = [{"url": spec["url"], "locator": spec["locator"]}]
    for key, value in spec["values"].items():
        if "." in key:
            group, name = key.split(".", 1)
            card[group][name] = value
        else:
            card[key] = value
        card["field_resolution"][key] = {
            "state": "not_applicable" if key == "evidence.target_construct" else "reported",
            "value": None if key == "evidence.target_construct" else value,
            "reason": "Checked directly in the owner article; claims about a model, anatomical map and biological validation are separated.",
            "checked_at": DATE, "locators": locator,
        }
    card["validation"].update({
        "screening_status": "included_context",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "not_applicable",
        "cross_subject": "not_applicable",
        "external_validation": "not_applicable",
        "calibration": "not_applicable",
        "uncertainty": "not_applicable",
    })
    for name in ("split_unit", "cross_subject", "external_validation", "calibration", "uncertainty"):
        card["field_resolution"][f"validation.{name}"] = {
            "state": "not_applicable", "value": None,
            "reason": "Owner article describes an anatomical resource or demonstration, not a patient-level predictive model.",
            "checked_at": DATE, "locators": locator,
        }
    card["field_resolution"]["validation.checked_at"] = {
        "state": "reported", "value": DATE, "reason": "Owner page rechecked on this date.",
        "checked_at": DATE, "locators": locator,
    }
    card["field_resolution"]["evidence.sample_size"] = {
        "state": "not_applicable", "value": None,
        "reason": "No independent experimental cohort is reported in this owner communication.",
        "checked_at": DATE, "locators": locator,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    ledger = json.loads((DATA / "src07-coverage-ledger-2026-09-25.json").read_text(encoding="utf-8"))
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    cards = {s["id"]: s for s in records["sources"]}
    rows = {r["source_id"]: r for r in ledger["rows"]}
    assert all(rows[sid]["route"] == "primary_route_pending" for sid in SPECS)
    assert cards["S368"]["метод"] == "Connectome simulation"
    for sid, spec in SPECS.items():
        update_card(cards[sid], spec)
        rows[sid]["route"] = "primary_route_screened"
        rows[sid]["evidence_artifacts"] = ["src07-three-owner-pages-review-2026-09-25.json"]
        rows[sid]["remaining"] = "Later dated owner-page refresh; any linked peer-reviewed study must be evaluated independently."
    ledger["meta"]["route_counts"] = dict(sorted(Counter(r["route"] for r in ledger["rows"]).items()))
    ledger["primary_route_pending_source_ids"] = [r["source_id"] for r in ledger["rows"] if r["route"] == "primary_route_pending"]
    assert ledger["primary_route_pending_source_ids"] == ["S099", "S144", "S245", "S272"]
    completeness.update(completeness_summary(records["sources"]))
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE, "status": "owner_pages_primary_text_checked"},
        "entries": [{"source_id": sid, "url": spec["url"], "locator": spec["locator"], "decision": spec["boundary"]} for sid, spec in SPECS.items()],
        "same_project_note": "S296 is the March 7 announcement and S253 the March 10 technical description of one Eon fly embodiment demonstration; they are not independent replications.",
        "remaining": "Four patent owner routes, publisher correction/preprint relation checks, and later dated refresh remain for SRC-07.",
    }
    if not args.apply:
        print(f"Dry run: corrected {len(SPECS)} owner-page cards; pending={ledger['primary_route_pending_source_ids']}")
        return
    todo = (ROOT / "TODO.md").read_text(encoding="utf-8")
    needle = "- [ ] **SRC-08.**"
    assert todo.count(needle) == 1
    note = "  Адресный просмотр страниц владельцев исправил `S253`, `S296`, `S368`: два поста Eon описывают одну виртуальную демонстрацию, мышиный коннектом остаётся будущей целью; статья Google от 03.09, обновлённая 21.09, описывает анатомическую карту, а не симуляцию. Статусы доступа и модальности в карточках приведены к первичным текстам; реестр SRC-07 теперь содержит 4 непроверенных патентных маршрута. См. `data/src07-three-owner-pages-review-2026-09-25.json`.\n"
    todo = todo.replace(needle, note + needle)
    readme = (DATA / "README.md").read_text(encoding="utf-8")
    readme = readme.replace("- `archive/`", "- `src07-three-owner-pages-review-2026-09-25.json` — Eon demo identity and Google anatomy-versus-simulation corrections;\n- `archive/`")
    snapshot = snapshot_repository(DATA, label="pre-src07-three-owner-pages-review")
    for name, obj in (("records.json", records), ("src07-coverage-ledger-2026-09-25.json", ledger), ("completeness-report.json", completeness), ("src07-three-owner-pages-review-2026-09-25.json", audit)):
        atomic_write_json(DATA / name, obj)
    (ROOT / "TODO.md").write_text(todo, encoding="utf-8", newline="\n")
    (DATA / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    print(f"Corrected owner-page cards; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
