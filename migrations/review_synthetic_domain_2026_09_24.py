"""Reconcile real-data use and evaluation boundaries in synthetic pain studies."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from service.completeness import completeness_summary, migrate_record
from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-24"
AUDIT = "synthetic-domain-audit.json"

# Each dimension is (state, value, primary locator). Terminal states describe
# what the accessible source establishes, never an inferred negative result.
SPECS: dict[str, dict[str, Any]] = {
    "S035": {
        "url": "https://link.springer.com/chapter/10.1007/978-3-031-88220-3_11",
        "dimensions": {
            "real_data_provenance": ("unavailable_after_search", None, "Publisher chapter preview: abstract and metadata only; methods and provenance inaccessible"),
            "leakage_control": ("unavailable_after_search", None, "Publisher chapter preview: no accessible fold or augmentation leakage protocol"),
            "split_unit": ("unavailable_after_search", None, "Publisher chapter preview: no accessible split method"),
            "external_test": ("unavailable_after_search", None, "Publisher chapter preview: no accessible independent test description"),
        },
    },
    "S083": {
        "url": "https://arxiv.org/html/2407.19811v1",
        "dataset": "SpeakingFaces for RGB-to-thermal GAN; DigiFace-1M, AffectNet, RAF-DB and Compound FEE-DB for feature pretraining; BioVid Part A for pain recognition",
        "notes": "The GAN was trained on paired SpeakingFaces images, then synthetic thermal images were derived from BioVid RGB videos. BioVid Part A recognition used 87 participants and 8,700 clips under leave-one-subject-out cross-validation. Dataset-level pretraining lineage is described, but an explicit identity-overlap audit across pretraining sets and BioVid is not reported. Table VIII juxtaposes another paper's MIntPAIN results; this model was not tested there.",
        "validation": {"split_unit": "participant", "cross_subject": "yes", "external_validation": "no"},
        "remove_risk": {"synthetic_only", "missing_cross_subject_validation"},
        "dimensions": {
            "real_data_provenance": ("reported", "SpeakingFaces paired RGB/thermal data train the GAN; several facial databases pretrain features; BioVid Part A real RGB videos supply the pain labels and test folds", "Sections III-E and IV; Table I; BioVid Part A, 87 people and 8,700 clips"),
            "leakage_control": ("reported", "BioVid recognition uses LOSO; whether any identity overlaps among external pretraining sets and BioVid is not documented", "Sections III-E and IV: pretraining datasets and LOSO, without cross-dataset identity matching"),
            "split_unit": ("reported", "Participant; leave-one-subject-out on BioVid Part A", "Section IV, final paragraph: LOSO"),
            "external_test": ("reported", "No independent external model test; MIntPAIN appears only as another study's result in Table VIII", "Section V, Table VIII: separate MIntPAIN and 'Our BioVid' rows"),
        },
    },
    "S084": {
        "url": "https://link.springer.com/article/10.1186/s12938-026-01561-2",
        "dataset": "UNBC-McMaster and UofR real images; UofR driver expressions transferred onto 250 generated identities; synthetic pain and neutral images augment classifier training",
        "notes": "Expression transfer uses UNBC and UofR real images. The pairwise detector uses full UNBC plus fivefold UofR/synthetic training and evaluates UofR dementia images. Authors exclude synthetic images derived from the test fold, but do not specify whether UofR folds are participant-disjoint or whether the expression-transfer model and driver pool exclude all test identities. No independent external test cohort is reported.",
        "validation": {"split_unit": "not_reported", "cross_subject": "not_reported", "external_validation": "no"},
        "remove_risk": {"synthetic_only"},
        "dimensions": {
            "real_data_provenance": ("reported", "UNBC trains generator and classifier; UofR supplies 394 driver frames and classifier training/test data; 250 generated identities produce 197,000 synthetic images", "Methods, Datasets, Generation of synthetic datasets and Pairwise pain detection model training"),
            "leakage_control": ("reported", "Authors exclude synthetic images corresponding to test-fold expressions; generator-training and driver-identity exclusion from UofR test folds is not established", "Methods, Pairwise pain detection model training: fivefold protocol and test-fold synthetic exclusion; compare Datasets"),
            "split_unit": ("not_reported", None, "Methods, Pairwise pain detection model training: fivefold UofR cross-validation is named, but frame/video/person grouping is not stated"),
            "external_test": ("reported", "No separate external cohort: UofR dementia images are the fivefold test target, while all UNBC data are used in training", "Methods, Pairwise pain detection model training; Results, Downstream task performance"),
        },
    },
    "S088": {
        "url": "https://doi.org/10.1109/ISDA70544.2026.11606012",
        "dimensions": {
            "real_data_provenance": ("unavailable_after_search", None, "Publisher DOI/Crossref metadata: full methods and dataset provenance inaccessible"),
            "leakage_control": ("unavailable_after_search", None, "Publisher DOI/Crossref metadata: no accessible adaptation or test leakage protocol"),
            "split_unit": ("unavailable_after_search", None, "Publisher DOI/Crossref metadata: no accessible split method"),
            "external_test": ("unavailable_after_search", None, "Publisher DOI/Crossref metadata: no accessible independent test description"),
        },
    },
    "S149": {
        "url": "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2026.1827727/full",
        "notes": "Synthetic-source unsupervised domain adaptation, termed zero-shot only in the qualified sense of zero labeled real target examples. Five-subject UNBC validation informed hyperparameters. Stage 2/3 used the full unlabeled real pool in every test fold, without excluding frames from test subjects; authors acknowledge unquantified optimistic bias. Test pain labels were not used in training. All three test benchmarks entered unlabeled adaptation in at least one condition, so none is a fully independent external validation cohort.",
        "validation": {"split_unit": "participant", "cross_subject": "yes", "external_validation": "no"},
        "remove_risk": {"synthetic_only"},
        "dimensions": {
            "real_data_provenance": ("reported", "50,000 labeled synthetic scenarios; approximately 8,000 unlabeled real recordings for adaptation; UNBC, BioVid and neonatal labeled benchmark folds for evaluation", "Sections 2.4, 3.1.2 and 4.1"),
            "leakage_control": ("reported", "Five-subject UNBC validation tuned hyperparameters; all folds used full unlabeled real pool without test-subject exclusion; no test pain labels were used for training or selection", "Section 4.7 Experimental protocol and leakage controls"),
            "split_unit": ("reported", "Participant-disjoint labeled test folds; unlabeled adaptation pool is not restricted per participant/fold", "Sections 4.1 and 4.7"),
            "external_test": ("reported", "No fully held-out fourth external dataset; three benchmark datasets contributed unlabeled real adaptation data in at least one condition", "Section 6.8.1.4 Absence of a fourth, fully external dataset"),
        },
    },
    "S192": {
        "url": "https://arxiv.org/html/2409.11635",
        "notes": "PainDiffusion generates expressions for simulation, not pain scores. BioVid Part C real recordings from 87 subjects train and assess generation; 61 subjects are in training and 26 in validation. Clinician preference assesses appearance, not real-patient pain prediction or an external clinical cohort.",
        "validation": {"split_unit": "participant", "cross_subject": "yes", "external_validation": "no"},
        "remove_risk": {"synthetic_only", "missing_cross_subject_validation"},
        "dimensions": {
            "real_data_provenance": ("reported", "BioVid Part C real video, biomedical and heat-stimulus streams from 87 subjects train and assess the expression generator", "Sections I and IV-A Dataset"),
            "leakage_control": ("reported", "61 training and 26 validation subjects are separate; no additional independent-site validation is reported", "Section IV-A Dataset"),
            "split_unit": ("reported", "Participant; 61 subjects train and 26 subjects validate", "Section IV-A Dataset"),
            "external_test": ("reported", "No independent external dataset; clinician preference study evaluates generated expressions from BioVid-conditioned samples", "Sections I and IV; qualitative results"),
        },
    },
    "S748": {
        "url": "https://www.mdpi.com/2073-431X/15/2/127",
        "dimensions": {
            "real_data_provenance": ("reported", "Publisher abstract names X-ITE and BioVid as evaluation datasets; exact augmentation input lineage remains inaccessible", "Publisher abstract and issue page; full methods returned HTTP 429 on 2026-09-24"),
            "leakage_control": ("unavailable_after_search", None, "Publisher full methods returned HTTP 429; no accessible fold-specific augmentation control"),
            "split_unit": ("unavailable_after_search", None, "Publisher full methods returned HTTP 429; abstract does not state person/video/clip grouping"),
            "external_test": ("unavailable_after_search", None, "Publisher full methods returned HTTP 429; abstract does not establish untouched external cohort"),
        },
    },
}


def _audit() -> dict[str, Any]:
    entries = []
    for source_id, spec in SPECS.items():
        extraction = {}
        for dimension, (state, value, locator) in spec["dimensions"].items():
            extraction[dimension] = {
                "state": state,
                "value": value,
                "reason": "Extracted from primary material." if state == "reported" else locator,
                "checked_at": DATE,
                "locators": [{"url": spec["url"], "locator": locator}],
            }
        entries.append({"source_id": source_id, "extraction": extraction})
    return {
        "meta": {"schema_version": "1.0.0", "generated_at": DATE, "records_count": len(entries), "gate": "G0_REVISE", "scope": "Empirical synthetic pain and domain-adaptation sources; S224 is code for S149, not independent empirical evidence"},
        "construct_boundary": "Generated images or expressions, stimulus-conditioned video, and pain estimation are different endpoints. Unlabeled target data used in adaptation are still real data.",
        "entries": entries,
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    records = load_json(data_dir / "records.json")
    updated = []
    for original in records["sources"]:
        source_id = original["id"]
        if source_id not in SPECS:
            updated.append(original)
            continue
        spec = SPECS[source_id]
        record = deepcopy(original)
        changed: list[str] = []
        if "dataset" in spec:
            record["датасет"] = spec["dataset"]
            changed.append("датасет")
        if "notes" in spec:
            record["ограничения"] = spec["notes"]
            record["validation"]["notes"] = spec["notes"]
            changed.extend(("ограничения", "validation.notes"))
        if "validation" in spec:
            record["validation"].update(spec["validation"])
            changed.extend("validation." + name for name in spec["validation"])
        record["validation"]["checked_at"] = DATE
        record["risk_flags"] = sorted(set(record["risk_flags"]) - spec.get("remove_risk", set()))
        record = migrate_record(record, checked_at=DATE)
        for path in changed:
            record["field_resolution"][path]["locators"] = [{"url": spec["url"], "locator": "Primary full text, methods/results; " + path}]
        updated.append(record)
    records["sources"] = updated
    records["meta"]["updated_at"] = DATE
    by_id = {record["id"]: record for record in updated}
    clusters = load_json(data_dir / "clusters.json")
    for cluster in clusters["clusters"]:
        representative = cluster.get("представитель")
        if representative and representative.get("id") in SPECS:
            cluster["представитель"] = deepcopy(by_id[representative["id"]])
    clusters["meta"]["updated_at"] = DATE
    log = load_json(data_dir / "validation-log.json")
    log.setdefault("searches", []).append({"search_id": "SYNTH-DOMAIN-2026-09-24-01", "date": DATE, "stream": "Synthetic pain and domain adaptation primary full-text review", "query": "exact titles and DOI at publishers and arXiv", "urls_reviewed": [spec["url"] for spec in SPECS.values()], "source_ids": sorted(SPECS), "decision": "real-data provenance, leakage, split and independent test terminally documented"})
    log["meta"]["checked_at"] = DATE
    report = load_json(data_dir / "audit-report.json")
    report["meta"]["generated_at"] = DATE
    report["current_corpus"]["validation_statuses"] = dict(sorted(Counter(record["validation"]["status"] for record in updated).items()))
    report["synthetic_domain_audit"] = {"checked_at": DATE, "source_ids": sorted(SPECS), "artifact": AUDIT, "finding": "Unlabeled adaptation, fold leakage, split unit and independent external test separated."}
    completeness = load_json(data_dir / "completeness-report.json")
    completeness.update(completeness_summary(updated))
    completeness["meta"]["generated_at"] = DATE
    return {"records.json": records, "clusters.json": clusters, "validation-log.json": log, "audit-report.json": report, "completeness-report.json": completeness, AUDIT: _audit()}


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-synthetic-domain-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        result = validate_repository(target)
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-synthetic-domain-review")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
        result = validate_repository(DATA)
        if not result["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(result['errors'])}")
    print(json.dumps({"ok": True, "applied": args.apply, "reviewed": sorted(SPECS), "snapshot": str(snapshot) if snapshot else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
