"""Review S008 against the publisher PDF and its source-dataset article."""

# ruff: noqa: E501 -- preserve scientific caveats and section locators.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
PDF = "https://iopscience.iop.org/article/10.1088/2057-1976/ae34b4/pdf"
DATASET_ARTICLE = "https://www.nature.com/articles/s41467-018-06875-x"

VALUES = {
    "модальность": "Laser-evoked 65-channel EEG; parietal 20-frequency by 251-time-point masked time-frequency matrices after preprocessing",
    "задача": "Classify individually calibrated low versus high acute laser-stimulus intensity in healthy adults during the motor condition",
    "метод": "Five-layer 1D-CNN and DeepSHAP compared with SVM, LDA, KNN, RF and decision tree under participant LOSO. A label-informed cluster-permutation mask was computed on the complete cohort before the LOSO folds; z-score normalization was fitted within training folds.",
    "датасет": "Secondary analysis of Tiemann et al. 2018 Nature Communications 9:4487, DOI 10.1038/s41467-018-06875-x: motor-condition EEG from 50 of the source study's 51 healthy right-handed adults; low/high laser stimuli, 20 planned trials per intensity and participant.",
    "производительность": "Authors report mean participant-LOSO accuracy 95.85% +/- 5% on the selected 50-person cohort. Results section also reports 231 high and 152 low correct plus 9 and 8 errors over 400 test trials; that pooled confusion count gives 383/400 = 95.75%. The paper does not reconcile 400 reported test trials with its 50-person by 40-trial SHAP description.",
    "кросс_субъект": "Participant LOSO across 50 people, but label-informed feature-mask selection used the entire cohort before folds; the authors explicitly acknowledge possible optimistic bias.",
    "ограничения": "The label-informed permutation mask was selected using all subjects, including held-out subjects, before LOSO; authors acknowledge possible optimistic bias despite train-only z-scoring. The 400-trial confusion denominator is not reconciled with the 50 by 40 trial description, and its pooled accuracy differs from the reported mean. No independent external dataset, chronic clinical pain, ECAP or SCS outcome was tested. SHAP attribution is not a causal biomarker.",
}

LOCATORS = {
    "модальность": "Sections 2.2-2.4: EEG acquisition, preprocessing and masked 20 x 251 parietal TFR input",
    "задача": "Section 2.1: motor condition and individually adjusted low/high laser stimuli",
    "метод": "Sections 2.4-2.5: complete-cohort permutation mask before LOSO; CNN and classical baselines",
    "датасет": "Section 2.1 and reference 19: prior Tiemann et al. dataset; 51 source subjects, 50 motor-condition subjects",
    "производительность": "Sections 3.2-3.3: 95.85% mean, 400-test-trial confusion counts, and 50 x 40 SHAP matrix",
    "кросс_субъект": "Sections 2.4 and 2.5.2: complete-cohort supervised mask and participant LOSO",
    "ограничения": "Sections 2.4, 3.2-3.3 and Discussion: optimistic feature-selection bias, trial denominator and external-validation limit",
}


def updated() -> tuple[dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    source = next(item for item in records["sources"] if item["id"] == "S008")
    if source["validation"]["full_text_status"] != "metadata_only":
        raise ValueError("S008 has already been full-text reviewed")
    for key, value in VALUES.items():
        source[key] = value
        source["field_resolution"][key].update({
            "state": "reported", "value": value,
            "reason": "Checked in the publisher version of record; author-reported performance is retained with explicit preprocessing and denominator limits.",
            "checked_at": DATE,
            "locators": [{"url": PDF, "locator": LOCATORS[key]}],
        })
    source["evidence"]["population"] = "50 healthy right-handed adults in the motor-condition EEG subset of Tiemann et al. 2018"
    source["evidence"]["target_label"] = "Individually calibrated low versus high laser-stimulus intensity classes, not an independently measured chronic-pain outcome"
    for path, value, locator in [
        ("evidence.population", source["evidence"]["population"], "Section 2.1 and reference 19"),
        ("evidence.target_label", source["evidence"]["target_label"], "Section 2.1, low/high stimulus classes"),
    ]:
        source["field_resolution"][path].update({
            "state": "reported", "value": value,
            "reason": "The analyzed EEG subset and model target are explicit in the primary method.",
            "checked_at": DATE,
            "locators": [{"url": PDF, "locator": locator}, {"url": DATASET_ARTICLE, "locator": "Methods, motor condition and original EEG cohort"}],
        })
    source["validation"].update({
        "status": "verified_primary",
        "full_text_status": "checked",
        "checked_at": DATE,
        "notes": "Publisher version-of-record PDF (13 pages) was read through r.jina.ai text rendering because direct IOP requests returned a Radware CAPTCHA; primary source is the IOP PDF URL. Section 2.4 explicitly says a supervised permutation mask used the complete dataset before participant LOSO and acknowledges optimistic bias. Training-fold z-scoring does not remove this feature-selection leakage. Sections 3.2-3.3 give 400 test trials and a 50 x 40 trial SHAP matrix without a reconciliation. The original dataset is Tiemann et al. 2018 motor-condition EEG, not a new patient cohort.",
    })
    source["risk_flags"] = [flag for flag in source["risk_flags"] if flag != "metadata_only"]
    for path, value, locator in [
        ("validation.checked_at", DATE, "Publisher PDF Sections 2.1-4 checked on 2026-09-25"),
        ("validation.notes", source["validation"]["notes"], "Sections 2.4, 3.2-3.3 and Discussion"),
        ("validation.cross_subject", source["validation"]["cross_subject"], "Sections 2.4 and 2.5.2: LOSO after complete-cohort mask"),
        ("validation.external_validation", source["validation"]["external_validation"], "Discussion: independent external dataset not tested"),
    ]:
        source["field_resolution"][path].update({
            "state": "reported", "value": value,
            "reason": "Primary full text reviewed; participant holdout and external test are evaluated separately.",
            "checked_at": DATE,
            "locators": [{"url": PDF, "locator": locator}],
        })
    source["field_resolution"]["validation.uncertainty"].update({
        "state": "not_reported", "value": None,
        "reason": "The reported +/-5% is variation in subject-level accuracy, not calibrated predictive uncertainty for individual trials.",
        "checked_at": DATE,
        "locators": [{"url": PDF, "locator": "Section 3.2 and Figure 5; no calibrated predictive-uncertainty output"}],
    })
    matrix = json.loads((DATA / "evidence-matrix.json").read_text(encoding="utf-8"))
    row = next(item for item in matrix["rows"] if item["batch_id"] == "human-generalization-review-2026-09-24" and "S008" in item["source_ids"])
    row["verified_evidence"] = "Publisher full text Sections 2.1, 2.4-2.5 and 3.2-3.3 identifies the Tiemann 2018 motor EEG subset (50 healthy adults), participant LOSO, five classical baselines and author-reported 95.85% mean accuracy."
    row["limitations"] = "The complete-cohort label-informed permutation mask precedes LOSO, and the authors acknowledge optimistic bias. Reported 400 test-trial confusion counts yield 95.75%, while a 50 x 40 trial SHAP matrix is also described; the denominators are not reconciled. No external cohort, chronic pain, ECAP or SCS outcome; SHAP attribution is not causal."
    row["population_or_data"] = "50 healthy adults from the motor-condition subset of Tiemann et al. 2018 laser-evoked EEG"
    row["locators"] = [
        {"source_id": "S008", "url": PDF, "locator": "Sections 2.1, 2.4-2.5 and 3.2-3.3; Figure 5"},
        {"source_id": "S008", "url": DATASET_ARTICLE, "locator": "Methods, motor-condition cohort and EEG acquisition"},
    ]
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE, "source_id": "S008", "status": "primary_full_text_checked"},
        "primary_url": PDF,
        "retrieval": "Publisher PDF text rendered through https://r.jina.ai/https://iopscience.iop.org/article/10.1088/2057-1976/ae34b4/pdf; direct IOP PDF returned Radware CAPTCHA in this environment.",
        "source_dataset": {"doi": "10.1038/s41467-018-06875-x", "n_source": 51, "n_analyzed": 50, "assay": "motor-condition laser-evoked EEG"},
        "model_split": "Participant LOSO after complete-cohort supervised feature-mask selection; z-score fitted in training folds.",
        "reported_metric": "95.85% +/- 5% mean subject accuracy",
        "internal_denominator_issue": "Section 3.2: 383 correct of 400 test trials (95.75% pooled); Section 3.3: SHAP array described for 50 subjects x 40 trials. No reconciliation supplied.",
        "boundary": "Experimental stimulus class in healthy adults; no external clinical pain or SCS validation.",
    }
    return records, matrix, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, matrix, audit = updated()
    if not args.apply:
        print("Dry run: S008 full-text, source-dataset and leakage correction")
        return
    snapshot = snapshot_repository(DATA, label="pre-s008-publisher-fulltext-review")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "evidence-matrix.json", matrix)
    atomic_write_json(DATA / "s008-primary-fulltext-audit.json", audit)
    print(f"Reviewed S008 primary PDF; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
