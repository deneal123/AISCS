"""Prepare two bounded PA-04 citation leads for read-only stage review."""

# ruff: noqa: E501 -- source claims and primary locators are preserved verbatim.

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = json.loads((ROOT / "data/staging/source-record.template.json").read_text(encoding="utf-8"))
OUT = ROOT / "data/staging/inbox"
DATE = "2026-09-25"


def make_resolution(value: object, url: str, locator: str, path: str) -> dict:
    if value is None:
        return {
            "state": "not_applicable",
            "value": None,
            "reason": "No such identifier, exclusion, or standalone field applies to this source.",
            "checked_at": DATE,
            "locators": [{"url": url, "locator": locator}],
        }
    if value == "not_reported":
        state = "not_reported"
        reason = "The checked primary method does not report this validation component."
    elif value == "not_applicable":
        state = "not_applicable"
        reason = "No predictive model or corresponding validation is part of this study."
    else:
        state = "reported"
        reason = f"Extracted for {path} from the linked primary article."
    return {
        "state": state,
        "value": value if state == "reported" else None,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


def build(*, source_id: str, filename: str, title: str, authors: str, year: int,
          journal: str, modality: str, task: str, method: str, dataset: str,
          performance: str, limitations: str, doi: str, pmid: str, url: str,
          locator: str, stream: str, species: str, population: str,
          domain: str, modalities: list[str], sample: str,
          target: str, target_label: str, notes: str,
          risk_flags: list[str]) -> Path:
    source = deepcopy(TEMPLATE)
    values = {
        "название": title,
        "авторы": authors,
        "год": year,
        "издание": journal,
        "модальность": modality,
        "задача": task,
        "метод": method,
        "датасет": dataset,
        "производительность": performance,
        "кросс_субъект": "not_applicable: within-subject experimental observations, no prediction model",
        "релевантность": 5,
        "ограничения": limitations,
        "тип_источника": "SCS_специфика",
    }
    source.update(values)
    source["id"] = source_id
    source["identifiers"].update({"doi": doi, "pmid": pmid, "exact_url": url})
    source["provenance"].update({
        "import_source": f"data/staging/inbox/{filename}",
        "retrieved_at": DATE,
        "search_stream": stream,
        "query_or_seed": "PA-04 backward citation screen from S787 and related ECAP primary articles",
        "iteration": 6,
    })
    source["evidence"].update({
        "species": species,
        "population": population,
        "subject_domain": domain,
        "modalities": modalities,
        "sample_size": sample,
        "target_construct": target,
        "target_label": target_label,
        "access_status": "open",
        "evidence_role": "method_baseline" if stream == "NS-09" else "context_only",
    })
    source["validation"].update({
        "status": "verified_primary",
        "screening_status": "included_core" if stream == "NS-09" else "included_context",
        "full_text_status": "checked",
        "checked_at": DATE,
        "split_unit": "not_applicable",
        "cross_subject": "not_applicable",
        "external_validation": "not_applicable",
        "calibration": "not_applicable",
        "uncertainty": "not_reported",
        "exclusion_reason": None,
        "notes": notes,
    })
    source["risk_flags"] = risk_flags
    for field in source["field_resolution"]:
        if "." in field:
            section, name = field.split(".", 1)
            value = source[section][name]
        else:
            value = source[field]
        source["field_resolution"][field] = make_resolution(value, url, locator, field)
    out = OUT / filename
    out.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    first = build(
        source_id="S789",
        filename="pa04-gmel-frequency-2026-09-25.json",
        title="The Effect of Spinal Cord Stimulation Frequency on the Neural Response and Perceived Sensation in Patients With Chronic Pain",
        authors="Gerrit Eduard Gmel; Rosana Santos Escapa; John L Parker; Dave Mugan; Adnan Al-Kaisy; Stefano Palmisani",
        year=2021,
        journal="Frontiers in Neuroscience 15:625835",
        modality="Human epidural ECAP and reported stimulation sensation",
        task="Characterize how SCS pulse frequency changes ECAP amplitude per pulse and perceived paresthesia strength",
        method="Within-patient frequency sweeps at fixed stimulation current and pulse width (2-455 Hz)",
        dataset="20 chronic-pain patients recruited; 16 patients/22 analyzable ECAP sweeps; 13 patients/18 sensation sweeps",
        performance="ECAP amplitude fell as frequency rose, while reported stimulation sensation increased; no pain-relief endpoint measured",
        limitations="Within-patient sweeps without independent validation; high frequencies limited by discomfort; ECAP and paresthesia are not pain intensity or clinical SCS response.",
        doi="10.3389/fnins.2021.625835",
        pmid="33551738",
        url="https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2021.625835/full",
        locator="Methods > Patient Recruitment and Materials and Frequency Sweeps; Results > Figs 3-4; Discussion > final two paragraphs",
        stream="NS-09",
        species="Homo sapiens",
        population="Patients undergoing SCS trial for chronic back and/or leg neuropathic pain",
        domain="human_clinical",
        modalities=["ecap", "other"],
        sample="20 recruited; 16 patients/22 ECAP sweeps; 13 patients/18 sensation sweeps",
        target="ecap_neural_recruitment",
        target_label="ECAP amplitude per pulse and separately rated stimulation sensation across frequency sweeps",
        notes="Full publisher text checked. No analgesia or future patient outcome is assessed. Repeated sweeps do not increase the patient denominator. Gmel et al. 2023 (DOI 10.3389/fnins.2023.1297814) explicitly reuses this study setup and its 20 recruited patients for a distinct postsynaptic dorsal-column analysis; do not count as independent cohorts.",
        risk_flags=["ecap_not_pain_measure"],
    )
    second = build(
        source_id="S790",
        filename="pa04-versantvoort-rat-2026-09-25.json",
        title="Evoked compound action potential (ECAP)-controlled closed-loop spinal cord stimulation in an experimental model of neuropathic pain in rats",
        authors="Eline M Versantvoort; Birte E Dietz; Dave Mugan; Quoc C Vuong; Saimir Luli; Ilona Obara",
        year=2024,
        journal="Bioelectronic Medicine 10:2",
        modality="Rat spinal ECAP and paw-withdrawal behavior",
        task="Test ECAP-controlled closed-loop SCS in a spared-nerve-injury model",
        method="Six-contact epidural lead; 30-minute 50-Hz, 200-us ECAP-controlled stimulation; von Frey and acetone assays",
        dataset="45 adult male Sprague-Dawley rats total, including SNI and sham groups; per-assay group sizes vary",
        performance="ECAP target tracking and reduced mechanical and cold hypersensitivity in stimulated SNI rats; outcomes are von Frey paw-withdrawal threshold and acetone-evoked paw-withdrawal latency",
        limitations="Preclinical rat SNI experiment; behavioral hypersensitivity is not patient-reported pain. SCS-ON/OFF assignment was not randomized and the behavioral tester was not blinded. No human clinical efficacy or patient-level prognostic model.",
        doi="10.1186/s42234-023-00134-1",
        pmid="38195618",
        url="https://bioelecmed.biomedcentral.com/counter/pdf/10.1186/s42234-023-00134-1.pdf",
        locator="Methods pp. 2-3, Experimental design and assessment of mechanical/cold hypersensitivity; Results pp. 8-9, Fig. 8",
        stream="NS-10",
        species="Rattus norvegicus",
        population="Adult male Sprague-Dawley rats, spared nerve injury and sham controls",
        domain="animal_other",
        modalities=["ecap", "behavior"],
        sample="45 rats total; per-assay group denominators vary",
        target="protective_behavior",
        target_label="von Frey paw-withdrawal threshold and acetone-evoked paw-withdrawal latency; ECAP is the feedback signal",
        notes="Full primary PDF checked. SCS-ON/OFF assignment was not randomized and the behavioral tester was not blinded (Methods > Experimental design). These behavioral proxies are not human pain reports. Avoid claiming direct ECAP-to-pain prediction.",
        risk_flags=["animal_to_human_transfer_unvalidated", "ecap_not_pain_measure"],
    )
    print(first)
    print(second)


if __name__ == "__main__":
    main()
