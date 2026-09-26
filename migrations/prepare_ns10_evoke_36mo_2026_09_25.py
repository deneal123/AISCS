"""Prepare the 36-month EVOKE follow-up from the deposited full article."""

# ruff: noqa: E501 -- preserve primary article sections and denominators.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns10-evoke-36mo-2024.json"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC11103285/"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S781":
        raise ValueError("Unexpected candidate ID")
    record.update({
        "авторы": "Nagy A Mekhail; Robert M Levy; Timothy R Deer; Leonardo Kapural; Sean Li; Kasra Amirdelfan; Jason E Pope; Corey W Hunter; Steven M Rosen; Shrif J Costandi; Steven M Falowski; Abram H Burgher; Christopher A Gilmore; Farooq A Qureshi; Peter S Staats; James Scowcroft; Tory McJunkin; Jonathan Carlson; Christopher K Kim; Michael I Yang; Thomas Stauss; Erika A Petersen; Jonathan M Hagedorn; Richard Rauck; Jan W Kallewaard; Ganesan Baranidharan; Rod S Taylor; Lawrence Poree; Dan Brounstein; Rui V Duarte; Gerrit E Gmel; Robert Gorman; Ian Gould; Erin Hanson; Dean M Karantonis; Abeer Khurram; Angela Leitner; Dave Mugan; Milan Obradovic; Zhonghua Ouyang; John Parker; Peter Single; Nicole Soliday; EVOKE Study Group",
        "год": 2024,
        "издание": "Regional Anesthesia & Pain Medicine 49(5):346-354; online 27 August 2023",
        "модальность": "ECAP-controlled closed-loop versus fixed-output open-loop SCS with patient-reported pain, holistic response and device neural-activation measures",
        "задача": "Compare long-term clinical and neurophysiological outcomes of ECAP-controlled and open-loop SCS at 36 months",
        "метод": "Blinded randomized parallel-arm follow-up of NCT02924129; all 134 randomized patients included in the 36-month intention-to-treat pain analysis with last-value-carried-forward for missing values; crossover counted as failure in a secondary analysis",
        "датасет": "Same EVOKE randomized cohort as S779 and S780: 134 randomized (67/67), 113 implanted (59/54); group outcomes analyzed at 36 months",
        "производительность": "At 36 months, at least 50% overall back-and-leg pain reduction: 77.6% closed-loop versus 49.3% open-loop (difference 28.4%, 95% CI 12.8-43.9, p<0.001); at least 80% reduction: 49.3% versus 31.3% (difference 17.9%, 95% CI 1.6-34.2, p=0.032)",
        "кросс_субъект": "not_applicable: randomized therapy comparison, no preimplant prognostic model",
        "релевантность": 5,
        "ограничения": "The 36-month analysis was not prespecified. Last-value-carried-forward makes an assumption about missing outcomes. Both arms used the same device and ECAP-guided programming, limiting comparison with conventional open-loop care. This is the same NCT02924129 cohort as S779/S780, not independent replication; ECAP is a neural-feedback signal, not a direct pain measure. Patient-level data require sponsor request and are not openly downloadable.",
        "тип_источника": "метод",
    })
    record["identifiers"].update({"doi": "10.1136/rapm-2023-104751", "pmid": "37640452", "exact_url": URL})
    record["provenance"].update({
        "import_source": "NS-10 primary open full text via PubMed Central BioC XML",
        "retrieved_at": DATE, "search_stream": "NS-10",
        "query_or_seed": "EVOKE NCT02924129 36-month ECAP-controlled closed-loop randomized trial",
        "iteration": 4,
    })
    record["evidence"].update({
        "species": "Homo sapiens",
        "population": "Adults with chronic, intractable back and leg pain refractory to conservative therapy in the NCT02924129 randomized trial",
        "subject_domain": "human_clinical", "modalities": ["ecap", "clinical_outcome"],
        "sample_size": 134, "target_construct": "scs_response",
        "target_label": "At least 50% or 80% reduction in patient-reported overall back-and-leg pain at 36 months; additional holistic response composite",
        "access_status": "open", "evidence_role": "scs_ecap_validation",
    })
    record["validation"].update({
        "status": "verified_primary", "screening_status": "included_core",
        "full_text_status": "checked", "checked_at": DATE,
        "split_unit": "participant", "cross_subject": "not_applicable",
        "external_validation": "no", "calibration": "not_reported",
        "uncertainty": "yes", "exclusion_reason": None,
        "notes": "Full deposited article checked via NCBI PMC BioC XML. Same NCT02924129 cohort as S779/S780; 36-month analysis not prespecified. ECAP controls neural dose; patient-reported pain is separate. No prospective outcome-prediction model or external validation.",
    })
    record["relations"] = []
    record["risk_flags"] = ["ecap_not_pain_measure"]
    record = migrate_record(record, checked_at=DATE)
    locators = {
        "авторы": "Article byline and PubMed AuthorList",
        "год": "Citation: 2024 issue 49(5):346-354; 27 August 2023 online",
        "издание": "Article citation, Regional Anesthesia & Pain Medicine 49(5):346-354",
        "модальность": "Abstract Methods and Results; Results, Neural activation",
        "задача": "Abstract, Introduction",
        "метод": "Methods, Statistical analysis; Results, Summary of participation and crossover",
        "датасет": "Results, Summary of participation and crossover; Figure 2 CONSORT",
        "производительность": "Abstract Results; Results, Overall pain intensity; Figure 3",
        "кросс_субъект": "Methods: randomized intervention analysis, no preimplant predictor",
        "ограничения": "Discussion, Strengths and limitations; Methods, Statistical analysis; Data availability statement",
        "evidence.species": "Methods, Participants",
        "evidence.population": "Methods, Participants; Trial registration NCT02924129",
        "evidence.sample_size": "Results, Summary of participation: 134 randomized; Figure 2",
        "evidence.target_construct": "Abstract, Primary outcome",
        "evidence.target_label": "Methods, Statistical analysis; Results, Overall pain intensity",
        "validation.split_unit": "Methods, Statistical analysis: patient-randomized groups",
        "validation.cross_subject": "Methods: intervention trial, no prognostic cross-subject test",
        "validation.external_validation": "Methods: single multicenter randomized trial, no external predictor test",
        "validation.calibration": "Methods: no probabilistic predictive model",
        "validation.uncertainty": "Abstract Results: between-group 95% confidence intervals",
        "validation.notes": "Methods, Statistical analysis; Results; Discussion, Strengths and limitations",
    }
    for path, locator in locators.items():
        field = record["field_resolution"][path]
        field["reason"] = "Checked in the primary deposited full text; same-trial and outcome boundaries retained."
        field["locators"] = [{"url": URL, "locator": locator}]
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/37640452/", "locator": "PMID, DOI, PMCID and article citation"}
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
