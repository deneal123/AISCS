"""Populate the human pain dataset review batch from checked source pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "curation" / "st-resources" / "batches" / "st-batch-002.json"
TODAY = date.today().isoformat()


def searches(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"query": query, "url": url, "accessed_at": TODAY} for query, url in items]


def decision(
    resource_id: str,
    outcome: str,
    exact_url: str | None,
    searched: list[dict[str, str]],
    claims: list[str],
    limitations: list[str],
    purpose: str,
    note: str,
) -> dict:
    return {
        "resource_id": resource_id,
        "decision": outcome,
        "exact_url": exact_url,
        "checked_at": TODAY,
        "searches": searched,
        "verified_claims": claims,
        "limitations": limitations,
        "corrected_purpose": purpose,
        "note": note,
    }


def main() -> None:
    payload = load_json(PATH)
    payload["meta"].update({"status": "reviewed", "reviewed_at": TODAY})
    payload["decisions"] = [
        decision(
            "ST034",
            "verified_primary",
            "https://zenodo.org/records/17704417",
            searches(
                (
                    "PainMotion Dataset DOMS musculoskeletal disorders",
                    "https://zenodo.org/records/17704417",
                )
            ),
            [
                "Zenodo record 10.5281/zenodo.17704417 provides ECG, sEMG, upper-limb inertial data and binary self-reported pain labels.",
                "The record describes 17 healthy participants with DOMS and 6 participants with shoulder musculoskeletal disorders.",
            ],
            [
                "Labels are binary self-reports collected during industrial tasks, not a continuous clinical pain endpoint.",
                "Files total 12.5 GB; this audit checked metadata and file inventory, not the signal contents.",
            ],
            "Multimodal human musculoskeletal-pain dataset with ECG, sEMG, IMU and binary self-report labels.",
            "Version 1.0.1 and the exact Zenodo DOI were confirmed.",
        ),
        decision(
            "ST035",
            "verified_primary",
            "https://www.ucl.ac.uk/uclic/research/affective-computing/emopain-dataset",
            searches(
                (
                    "UCL EmoPain dataset chronic pain IMU sEMG",
                    "https://www.ucl.ac.uk/uclic/research/affective-computing/emopain-dataset",
                )
            ),
            [
                "The UCL page describes 18 IMUs and four sEMG sensors for 12 healthy and 18 chronic-pain participants.",
                "Protective behaviour was independently annotated by four domain experts.",
            ],
            [
                "Access to the body-movement component requires contacting the dataset owner.",
                "Protective behaviour is not interchangeable with pain intensity or a clinical outcome.",
            ],
            "Controlled-access movement, sEMG and annotation resource for chronic-pain protective behaviour research.",
            "The former generic NIT link was replaced with the official UCL dataset page.",
        ),
        decision(
            "ST036",
            "rejected",
            None,
            searches(
                (
                    "LENS Dataset sEMG NIRS jaw clenching pain",
                    "https://www.google.com/search?q=%22LENS+Dataset%22+sEMG+NIRS+jaw+clenching+pain",
                ),
                ("site:odesi.ca LENS pain dataset", "https://odesi.ca/"),
            ),
            [],
            [
                "No primary dataset matching the imported name, modalities and jaw-clenching description was found.",
                "The supplied odesi.ca domain is a catalogue landing page and does not identify this resource.",
            ],
            "Rejected candidate: no stable identifier or exact primary record could be established.",
            "Do not use the imported modality or task claims as facts unless a primary record is supplied.",
        ),
        decision(
            "ST037",
            "verified_primary",
            "https://osf.io/mj9xr/",
            searches(
                ("OSF mj9xr metadata", "https://api.osf.io/v2/nodes/mj9xr/"),
                ("OSF mj9xr file inventory", "https://api.osf.io/v2/nodes/mj9xr/files/osfstorage/"),
            ),
            [
                "OSF identifies the project as Effects of analgesics on EEG biomarkers of chronic pain.",
                "The public storage contains BIDS archives and clinical spreadsheets for two cohorts.",
            ],
            [
                "The imported name OpenPain was incorrect and has been removed from the resource purpose.",
                "The multi-gigabyte archives were not downloaded or independently checked for BIDS validity.",
            ],
            "Public OSF project containing BIDS EEG archives and clinical variables for analgesic effects on chronic-pain EEG biomarkers.",
            "Verified through the OSF API because the browser landing page returns an automated-access error.",
        ),
        decision(
            "ST038",
            "partially_verified",
            "https://osf.io/srpbg/",
            searches(
                ("OSF hbkmx", "https://api.osf.io/v2/nodes/hbkmx/"),
                (
                    "PainLabMunich public resting-state EEG chronic pain dataset",
                    "https://api.osf.io/v2/nodes/srpbg/",
                ),
            ),
            [
                "A public PainLabMunich OSF project exists for resting-state EEG from 101 chronic-pain patients and 88 matched controls.",
            ],
            [
                "The imported OSF identifier hbkmx returns 404 and could not be validated.",
                "The replacement srpbg project is a specific PainLabMunich dataset, not a generic record for every lab dataset.",
            ],
            "PainLabMunich resting-state EEG dataset for chronic-pain microstate analysis, represented by the verified srpbg project.",
            "Corrected to the closest documented primary project; original identifier remains disproven.",
        ),
        decision(
            "ST039",
            "verified_primary",
            "https://data.mendeley.com/datasets/yj52xrfgtz/4",
            searches(
                (
                    "chronic neuropathic pain EEG painDETECT BPI 36",
                    "https://data.mendeley.com/datasets/yj52xrfgtz/4",
                )
            ),
            [
                "Mendeley Data DOI 10.17632/yj52xrfgtz.4 contains resting-state EEG and questionnaire data from 36 chronic neuropathic-pain patients.",
                "The protocol includes five minutes eyes open, five minutes eyes closed, painDETECT and Brief Pain Inventory reports.",
            ],
            [
                "The dataset has no healthy control group and contains heterogeneous etiologies and medication exposure.",
                "It supports within-cohort association or stratification, not causal or population-wide pain inference.",
            ],
            "Resting-state EEG plus painDETECT and Brief Pain Inventory data for 36 chronic neuropathic-pain patients.",
            "Exact Mendeley version and data article were matched.",
        ),
        decision(
            "ST040",
            "verified_primary",
            "https://openneuro.org/datasets/ds008115",
            searches(
                ("OpenNeuro ds008115 ValidPain2", "https://openneuro.org/datasets/ds008115"),
                (
                    "EEGDash DS008115 metadata",
                    "https://eegdash.org/api/dataset/eegdash.dataset.DS008115.html",
                ),
            ),
            [
                "OpenNeuro identifier ds008115 resolves to the ValidPain2 EEG dataset under DOI 10.18112/openneuro.ds008115.v1.0.0.",
                "Catalogue metadata reports 180 mechanically ventilated intensive-care patients, four EEG channels and three clinical-procedure tasks.",
            ],
            [
                "Patients were unable to self-report pain; the target concerns responsiveness to potentially nociceptive procedures, not subjective pain intensity.",
                "Signal files were not downloaded or independently quality-controlled in this audit.",
            ],
            "Frontal EEG dataset for responsiveness to potentially nociceptive procedures in mechanically ventilated ICU patients.",
            "Nociception-monitor output and behavioural responsiveness must remain distinct from subjective pain.",
        ),
        decision(
            "ST041",
            "verified_primary",
            "https://nemar.org/dataset/on006921",
            searches(
                ("NEMAR phantom limb pain resting-state EEG", "https://nemar.org/dataset/on006921")
            ),
            [
                "NEMAR on006921 provides 64/128-channel resting-state EEG from 38 participants across amputee and intact-control groups.",
                "The BIDS dataset includes eyes-open/eyes-closed tasks and pain-related phenotype data.",
            ],
            [
                "This is a resting-state group-comparison resource, not an evoked pain-intensity dataset.",
                "NEMAR data-quality summaries were not yet published on the checked page.",
            ],
            "High-density resting-state EEG and phenotype data for phantom-limb-pain, amputee-control and intact-control groups.",
            "OpenNeuro DOI 10.18112/openneuro.ds006921.v1.1.1 is linked by NEMAR.",
        ),
        decision(
            "ST042",
            "verified_primary",
            "https://openneuro.org/datasets/ds006374",
            searches(
                (
                    "OpenNeuro expectation repetition suppression nociception",
                    "https://openneuro.org/datasets/ds006374",
                )
            ),
            [
                "OpenNeuro ds006374 contains EEG and behavioural data from 36 participants under DOI 10.18112/openneuro.ds006374.v1.0.0.",
                "The listed tasks are calibration, expectation/repetition-suppression and detection.",
            ],
            [
                "The source supports study of expectation and nociceptive responses; it does not establish that expectation modulates repetition suppression.",
                "The repository reports many BIDS warnings, so preprocessing assumptions require review before use.",
            ],
            "EEG/behavioural dataset for testing expectation effects on repetition suppression in nociception.",
            "The imported causal-sounding summary was narrowed to the study question.",
        ),
        decision(
            "ST043",
            "verified_primary",
            "https://figshare.com/articles/dataset/28740260",
            searches(
                (
                    "MOABB Zuo2025 knee pain",
                    "https://moabb.neurotechx.com/docs/generated/moabb.datasets.Zuo2025.html",
                ),
                (
                    "Zuo2025 Figshare dataset 28740260",
                    "https://figshare.com/articles/dataset/28740260",
                ),
            ),
            [
                "The dataset contains 30-channel, 500-Hz EEG from 30 knee-pain patients performing left/right leg motor imagery.",
                "The associated publication DOI is 10.1038/s41597-025-05767-2.",
            ],
            [
                "The target is motor-imagery class, not pain intensity or nociceptive response.",
                "MOABB reports 32 of 150 raw sessions missing and a label-mapping inconsistency between README and events metadata.",
            ],
            "Lower-limb motor-imagery EEG dataset from knee-pain patients; useful as clinical-domain representation data, not a pain-label benchmark.",
            "Exact Figshare record and known completeness caveats were captured.",
        ),
        decision(
            "ST044",
            "verified_primary",
            "https://data.mendeley.com/datasets/kb9pb6tzkg/2",
            searches(
                (
                    "Mendeley evoked fNIRS thermal QST",
                    "https://data.mendeley.com/datasets/kb9pb6tzkg/2",
                )
            ),
            [
                "Mendeley Data DOI 10.17632/kb9pb6tzkg.2 provides fNIRS data and code for 16 participants across cold/heat threshold and tolerance tasks.",
                "The record includes raw and filtered haemoglobin signals plus k-fold and leave-one-subject-out training code.",
            ],
            [
                "Threshold/tolerance task labels are protocol-derived and are not interchangeable with clinical pain states.",
                "Published model results and code reproducibility were not independently rerun.",
            ],
            "Evoked fNIRS and code for thermal quantitative sensory testing across cold/heat threshold and tolerance conditions.",
            "Updated to the current Mendeley version 2 record.",
        ),
        decision(
            "ST045",
            "verified_primary",
            "https://www.nemar.org/dataset/on005776",
            searches(
                (
                    "NEMAR Electrical Thermal FingerTapping 2015",
                    "https://www.nemar.org/dataset/on005776",
                )
            ),
            [
                "NEMAR on005776 contains NIRS data from 11 participants across electrical, thermal, finger-tapping, imagery and resting tasks.",
                "The record links OpenNeuro DOI 10.18112/openneuro.ds005776.v1.0.1 and two associated publications.",
            ],
            [
                "The catalogue description mixes painful stimulation and motor tasks; task-level event semantics must be inspected before modeling.",
                "No independent signal-quality analysis was performed.",
            ],
            "BIDS fNIRS dataset combining noxious electrical/thermal stimulation and motor-control tasks.",
            "Exact NEMAR/OpenNeuro identifiers were recorded.",
        ),
        decision(
            "ST046",
            "verified_primary",
            "https://www.nemar.org/dataset/on005777",
            searches(
                ("NEMAR Electrical Morphine Placebo 2018", "https://www.nemar.org/dataset/on005777")
            ),
            [
                "NEMAR on005777 contains NIRS data from 14 participants under baseline, morphine and placebo conditions.",
                "The record links OpenNeuro DOI 10.18112/openneuro.ds005777.v1.0.1 and article DOI 10.3389/fnhum.2018.00394.",
            ],
            [
                "The small pharmacological experiment is not a general clinical-pain dataset.",
                "No independent signal-quality or treatment-effect reproduction was performed.",
            ],
            "BIDS fNIRS dataset for neural responses to electrical stimulation under baseline, morphine and placebo conditions.",
            "Exact NEMAR/OpenNeuro identifiers were recorded.",
        ),
        decision(
            "ST047",
            "verified_primary",
            "https://www.nitrc.org/projects/yucel18pain/",
            searches(
                (
                    "NITRC yucel18pain morphine placebo fNIRS",
                    "https://www.nitrc.org/projects/yucel18pain/",
                )
            ),
            [
                "The NITRC project page describes fNIRS during electrical pain under morphine and placebo conditions.",
                "The page links the same 2018 study represented by the NEMAR/OpenNeuro on005777 record.",
            ],
            [
                "This is an alternate project portal for the ST046 study, not an independent cohort.",
                "The checked NITRC page does not establish that downloadable files remain available there.",
            ],
            "Legacy NITRC project page for the morphine/placebo fNIRS study also preserved in NEMAR/OpenNeuro.",
            "Count as source provenance, not as a second independent dataset.",
        ),
        decision(
            "ST048",
            "verified_primary",
            "https://www.nitrc.org/projects/yucel15pain/",
            searches(
                (
                    "NITRC yucel15pain electrical pain fNIRS",
                    "https://www.nitrc.org/projects/yucel15pain/",
                )
            ),
            [
                "The NITRC page describes fNIRS from 11 participants receiving innocuous and noxious electrical stimuli.",
                "The project links publication DOI 10.1038/srep09469.",
            ],
            [
                "This portal overlaps the electrical-stimulation component represented in ST045 and is not an independent cohort.",
                "Thermal and motor tasks available in the later NEMAR package are not established by this page alone.",
            ],
            "Legacy NITRC page for the 11-participant electrical-stimulation fNIRS study represented in the broader NEMAR package.",
            "Count as source provenance, not as a second independent dataset.",
        ),
    ]
    atomic_write_json(PATH, payload)
    print({"batch": payload["meta"]["batch_id"], "decisions": len(payload["decisions"])})


if __name__ == "__main__":
    main()
