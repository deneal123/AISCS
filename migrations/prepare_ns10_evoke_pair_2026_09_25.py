"""Rekey and verify the two EVOKE staging cards before publication."""

# ruff: noqa: E501 -- primary abstract and full-text locators are intentional.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "data/staging/inbox"
DATE = "2026-09-25"
LANCET = "https://pubmed.ncbi.nlm.nih.gov/31870766/"
JAMA = "https://jamanetwork.com/journals/jamaneurology/fullarticle/2788004"
FILES = (
    ("evoke-12mo-mekhail-2020-2026-09-25.json", "S776", "S779", LANCET),
    ("evoke-24mo-mekhail-2022-2026-09-25.json", "S777", "S780", JAMA),
)


def main() -> None:
    for filename, old_id, new_id, url in FILES:
        path = INBOX / filename
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["id"] != old_id:
            raise ValueError(f"Unexpected {filename} ID: {record['id']}")
        record["id"] = new_id
        record["provenance"].update({
            "search_stream": "NS-10", "retrieved_at": DATE,
            "query_or_seed": "NCT02924129 EVOKE closed-loop SCS randomized trial and 24-month secondary analysis",
            "iteration": 4,
        })
        if new_id == "S779":
            record["авторы"] = "Nagy Mekhail; Robert M. Levy; Timothy R. Deer; Leonardo Kapural; Sean Li; Kasra Amirdelfan; Corey W. Hunter; Steven M. Rosen; Shrif J. Costandi; Steven M. Falowski; Abram H. Burgher; Jason E. Pope; Christopher A. Gilmore; Farooq A. Qureshi; Peter S. Staats; James Scowcroft; Jonathan Carlson; Christopher K. Kim; Michael I. Yang; Thomas Stauss; Lawrence Poree; Evoke Study Group"
            record["validation"]["notes"] = "PubMed author abstract and Europe PMC bibliographic record checked; full Lancet method/tables were inaccessible. The byline excludes people listed only as investigators. Cohort NCT02924129 is the same trial as S780; denominators and outcomes are abstract-level."
        else:
            record["identifiers"]["exact_url"] = JAMA
            record["validation"]["notes"] = "JAMA full text checked: the 24-month report is a secondary analysis of NCT02924129, the same 134 randomized patients as S779. Figure 1 distinguishes all randomized primary-outcome analysis (LOCF, 67/67) from 24-month secondary-outcome completers (50/42). JAMA corrected Figure 4 in DOI 10.1001/jamaneurol.2022.0022; the correction is to the device-performance figure, not an independent trial."
        record = migrate_record(record, checked_at=DATE)
        locators = {
            "авторы": "Article byline; named study group is retained, investigators are not promoted to byline authors",
            "год": "Journal citation and online publication date",
            "издание": "Journal citation",
            "модальность": "Abstract Methods and Findings" if new_id == "S779" else "Methods, Interventions and Outcomes; Figure 4 device performance",
            "задача": "Abstract Background and Methods" if new_id == "S779" else "Abstract, Objective and Main Outcomes",
            "метод": "Abstract Methods: randomization, masking, trial arms and 3/12-month analyses" if new_id == "S779" else "Methods, Study Design and Statistical Analysis; Figure 1 CONSORT",
            "датасет": "Abstract Findings: 134 randomized, 125 at 3 months, 118 at 12 months" if new_id == "S779" else "Figure 1 CONSORT: 134 randomized; 50/42 complete 24-month visit",
            "производительность": "Abstract Findings: 3- and 12-month responder counts, differences and confidence intervals" if new_id == "S779" else "Abstract Results; Figure 2 and Table: 24-month pain responder outcomes",
            "ограничения": "Abstract only; full trial methods and missing-data handling not verified" if new_id == "S779" else "Figure 1 CONSORT; Limitations; corrected Figure 4 notice",
            "evidence.population": "Abstract Methods: chronic refractory back and leg pain; 13 US sites" if new_id == "S779" else "Methods, Participants and Figure 1",
            "evidence.sample_size": "Abstract Findings: 134 randomized (67/67)" if new_id == "S779" else "Figure 1 CONSORT: 67/67 randomized; 50/42 complete 24 months",
            "evidence.target_label": "Abstract Methods: at least 50% overall back-and-leg pain reduction without medication increase" if new_id == "S779" else "Methods, Outcomes: at least 50% and 80% pain reduction at 24 months",
            "validation.split_unit": "Abstract Methods: participant-randomized trial" if new_id == "S779" else "Methods, Randomization; Figure 1 CONSORT",
            "validation.notes": "PubMed abstract and Europe PMC bibliographic record; full text unavailable" if new_id == "S779" else "Methods, Results, Figure 1 and corrected Figure 4 notice",
        }
        for field_name, locator in locators.items():
            field = record["field_resolution"][field_name]
            field["value"] = record["авторы"] if field_name == "авторы" else field["value"]
            if field_name == "validation.notes":
                field["value"] = record["validation"]["notes"]
            field["reason"] = "Checked against the named primary locator; limits of accessible text retained."
            field["locators"] = [{"url": url, "locator": locator}]
        record["field_resolution"]["identifiers.exact_url"].update({
            "value": record["identifiers"]["exact_url"],
            "locators": [{"url": url, "locator": "Article identifier and publisher or PubMed landing page"}],
        })
        if new_id == "S780":
            record["field_resolution"]["validation.notes"]["locators"].append(
                {"url": "https://doi.org/10.1001/jamaneurol.2022.0022", "locator": "JAMA correction: Error in Figure 4"}
            )
        atomic_write_json(path, record)
        print(f"Prepared {new_id}: {path}")


if __name__ == "__main__":
    main()
