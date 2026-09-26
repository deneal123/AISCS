"""Replace S748 abstract-level claims with checked publisher PDF evidence."""

# ruff: noqa: E501 -- primary locators and study boundaries remain explicit.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
PDF = "https://mdpi-res.com/d_attachment/computers/computers-15-00127/article_deploy/computers-15-00127.pdf"
SHA256 = "1805489e984deb4673e0a3c2fd236a66167331acd82df5899e0e75175088a28f"


def locator(section: str) -> list[dict]:
    return [{"url": PDF, "locator": section}]


def resolution(value: object, section: str, reason: str) -> dict:
    return {
        "state": "reported",
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": locator(section),
    }


def update_field(source: dict, path: str, value: object, section: str, reason: str) -> None:
    if "." in path:
        head, tail = path.split(".", 1)
        source[head][tail] = value
    else:
        source[path] = value
    if path in source["field_resolution"]:
        source["field_resolution"][path] = resolution(value, section, reason)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    audit = json.loads((DATA / "synthetic-domain-audit.json").read_text(encoding="utf-8"))
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    source = next(x for x in records["sources"] if x["id"] == "S748")
    entry = next(x for x in audit["entries"] if x["source_id"] == "S748")
    row = next(x for x in matrix["rows"] if "S748" in x["source_ids"])
    if source["validation"]["full_text_status"] != "metadata_only":
        raise ValueError("S748 has already been upgraded")

    fields = {
        "Модальность": ("ECG, EDA and EMG physiological features; facial video excluded", "§4, pp. 8–9", "The article lists the analyzed signals for both datasets."),
        "Данные": ("X-ITE: 134 subjects, 30 selected as test subjects, 10 trials per subject; BioVid Part A: 87 recorded, 80 analyzed after seven exclusions", "§4 and §5.1, pp. 8–9", "The PDF reports dataset and analysis denominators."),
        "Результативность": ("X-ITE RBF-Patch-Net with ModMix: 87.1 ± 11.3% mean accuracy versus 86.4 ± 10.3% without augmentation; 12/30 subjects improved, 7 unchanged, 11 worsened. BioVid without augmentation: both compared models approximately 81% mean accuracy.", "§6.1 Table 1 and Figure 3, pp. 10–11; §6.2, p. 12", "The reported gains vary by subject; the BioVid analysis omits augmentation."),
        "Кросс_субъект": ("Yes: each X-ITE trial excludes the test subject from training; BioVid uses the remaining subjects as training", "§5.1 and §6.1, pp. 8–10", "The per-trial subject exclusion is explicit."),
        "Ограничения": ("Experimental thermal/electrical pain classification in healthy volunteers, not clinical SCS outcomes. X-ITE uses a participant-disjoint test subject in each trial, but the 30 subjects are not one fixed independent holdout across trials. ModMix improves mean accuracy by about 0.7 percentage points and worsens 11/30 subjects. BioVid final analysis omits augmentation; no independent external validation of ModMix or patient-level prospective validation is reported. Hyperparameter grid-search selection unit is unclear.", "§4–7, pp. 8–13", "Full-method review separates held-out test subjects from external clinical validation."),
        "evidence.population": ("Healthy X-ITE and BioVid participants; X-ITE 134 total/30 tested, BioVid 87 total/80 analyzed", "§4–5.1, pp. 8–9", "The paper states the denominators."),
        "evidence.modalities": (["ecg", "eda", "emg"], "§4, p. 8", "The experiments use physiological signals only."),
        "evidence.sample_size": ("X-ITE 134 subjects, 30 tested; BioVid 87 recorded, 80 analyzed", "§4–5.1, pp. 8–9", "Dataset and analyzed counts are reported separately."),
        "validation.split_unit": ("participant", "§5.1 and §6.1, pp. 8–10", "Each trial excludes the target test subject's data from its training pool."),
        "validation.cross_subject": ("yes", "§5.1 and §6.1, pp. 8–10", "Training observations are sampled from the other 133 or 79 participants, respectively."),
        "validation.external_validation": ("no", "§6.1–6.2, pp. 10–12", "BioVid uses a separate benchmark without the proposed augmentation in its final analysis; no external ModMix test is shown."),
        "validation.notes": ("Official publisher PDF checked (SHA-256 " + SHA256 + "). X-ITE tests 30 selected subjects with 10 participant-disjoint trials each; training uses 2500 observations from the other 133 subjects and 500 augmented training points. BioVid tests 80 analyzed subjects with 3000 observations drawn from the other subjects, five runs, and no augmentation in the final analysis. ModMix data filtering uses a network trained on original data; tuning selection and code-level fold reproduction were not established.", "§5.1–6.2, pp. 8–12", "Full PDF methods and results checked; unresolved implementation details remain explicit."),
    }
    by_label = {
        "Модальность": "модальность",
        "Данные": "датасет",
        "Результативность": "производительность",
        "Кросс_субъект": "кросс_субъект",
        "Ограничения": "ограничения",
    }
    for path, (value, section, reason) in fields.items():
        update_field(source, by_label.get(path, path), value, section, reason)
    source["validation"].update(status="verified_primary", full_text_status="checked", checked_at=DATE)
    source["provenance"]["retrieved_at"] = DATE
    source["risk_flags"] = [x for x in source["risk_flags"] if x not in {"metadata_only", "missing_cross_subject_validation"}]
    for path, value, section in [
        ("validation.checked_at", DATE, "§5.1–6.2, pp. 8–12"),
        ("provenance.retrieved_at", DATE, "Publisher PDF checked on 2026-09-25"),
    ]:
        update_field(source, path, value, section, "Primary PDF reviewed on this date.")

    entry["extraction"] = {
        "real_data_provenance": resolution("X-ITE 134 healthy participants and BioVid Part A 87 healthy participants (80 analyzed); physiological ECG, EDA and EMG features only; binary extreme labels", "§4 and §5.1, pp. 8–9", "Both real-data inputs and exclusions are stated."),
        "leakage_control": resolution("For each target participant, 2500 X-ITE training observations are sampled from the other 133 participants; 500 ModMix points are added to training. The paper does not give a code-level fold audit or explicit hyperparameter selection unit.", "§5.1–5.3 and §6.1, pp. 8–10", "The stated protocol excludes the tested person from the training sample; implementation details remain unverified."),
        "split_unit": resolution("participant (per-trial held-out person; not a fixed 30-person external cohort)", "§5.1 and §6.1, pp. 8–10", "The paper explicitly states the subject-exclusion rule."),
        "external_test": resolution("No external test of ModMix: BioVid final comparison omits augmentation after inconsistent preliminary results", "§6.2, p. 12", "The second benchmark tests the base RBF model and random forest without ModMix."),
    }
    row.update(
        population_or_data="X-ITE 134 subjects (30 tested); BioVid 87 subjects (80 analyzed)",
        verified_evidence="Publisher PDF §4–6.2: participant-disjoint per-trial X-ITE testing, 2500 training observations from the other 133 subjects and 500 augmented points; RBF-Patch-Net 87.1 ± 11.3% with ModMix versus 86.4 ± 10.3% without; BioVid final analysis has no augmentation.",
        limitations="Only binary experimental-pain extremes are used. X-ITE mean gain is about 0.7 percentage points and 11/30 tested subjects worsen. BioVid is not an external test of ModMix; no clinical pain, ECAP, SCS outcome or prospective patient validation. Code-level fold and tuning audit remain open.",
        permitted_conclusion="Participant-disjoint X-ITE proof of concept for physiological pain-class augmentation, with heterogeneous effect; no demonstrated clinical or external ModMix generalization.",
        locators=[{"source_id": "S748", "url": PDF, "locator": "§4–6.2, pp. 8–12; Table 1; Figure 3; PDF SHA-256 " + SHA256}],
    )
    completeness.update(completeness_summary(records["sources"]))
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-s748-modmix-fulltext-review")
        atomic_write_json(DATA / "records.json", records)
        atomic_write_json(DATA / "synthetic-domain-audit.json", audit)
        atomic_write_json(DATA / "evidence-matrix.json", matrix)
        atomic_write_json(DATA / "completeness-report.json", completeness)
        print(f"Applied S748 full-text review; snapshot: {snapshot}")
    else:
        print("Dry run: S748 publisher PDF reviewed")


if __name__ == "__main__":
    main()
