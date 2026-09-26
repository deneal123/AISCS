"""Prepare the primary cross-species mesoscale connectome comparison."""

# ruff: noqa: E501 -- keep primary method locators and scope limits explicit.

import json
from pathlib import Path

from service.completeness import migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/staging/inbox/ns05-betzel-mesoscale-2018.json"
URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC5783945/"
PUBLISHER = "https://www.nature.com/articles/s41467-017-02681-z"
DATE = "2026-09-25"


def main() -> None:
    record = json.loads(PATH.read_text(encoding="utf-8"))
    if record["id"] != "S772":
        raise ValueError("Candidate ID changed")
    record.update(
        {
            "авторы": "Richard F. Betzel; John D. Medaglia; Danielle S. Bassett",
            "год": 2018,
            "издание": "Nature Communications 9:346",
            "модальность": "Published inter-areal structural connectomes across Drosophila, mouse, rat, macaque and human; human functional connectivity and mouse gene co-expression as separate comparisons",
            "задача": "Compare assortative, core-periphery and disassortative mesoscale community organization across species",
            "метод": "Weighted stochastic blockmodel fitted to inter-areal connectomes and compared with modularity maximization over K=2-10 communities, with 250 runs per K; community-interaction motifs and diversity indices were analyzed",
            "датасет": "Previously published inter-areal connectomes in five species; Drosophila analysis is supplementary. The main text models group-representative human connectome data. Data availability states that study data are obtainable from authors on reasonable request.",
            "производительность": "In human data, weighted stochastic-blockmodel partitions aligned more strongly with functional-connectivity within-versus-between community contrast than modularity partitions; no cross-species transfer score or ECAP/SCS metric was reported",
            "кросс_субъект": "not_applicable: descriptive cross-species graph comparison, not a participant-disjoint predictive transfer test",
            "релевантность": 3,
            "ограничения": "The Drosophila and human graphs are compared at inter-areal mesoscale, not neuron-level FlyWire/VNC resolution. Human functional-connectivity corroboration does not validate a Drosophila-to-human dynamical representation, causal invariant, ECAP operator or SCS outcome.",
            "тип_источника": "метод",
        }
    )
    record["identifiers"].update(
        {
            "doi": "10.1038/s41467-017-02681-z",
            "pmid": "29367627",
            "exact_url": PUBLISHER,
        }
    )
    record["provenance"].update(
        {
            "import_source": "NS-05 primary publisher and Europe PMC full text",
            "retrieved_at": DATE,
            "search_stream": "NS-05",
            "query_or_seed": "cross-species connectome graph motif comparison Betzel Bassett",
            "iteration": 3,
        }
    )
    record["evidence"].update(
        {
            "species": "Drosophila melanogaster; mouse; rat; macaque; Homo sapiens",
            "population": "Published inter-areal connectomes across five species; group-representative human graph in main analysis",
            "subject_domain": "mixed",
            "modalities": ["connectome"],
            "sample_size": None,
            "target_construct": "not_applicable",
            "target_label": "Assortative, core-periphery and disassortative community motifs and motif diversity",
            "access_status": "open",
            "evidence_role": "context_only",
        }
    )
    record["validation"].update(
        {
            "status": "verified_primary",
            "screening_status": "included_context",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_applicable",
            "calibration": "not_applicable",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": "Publisher article and primary JATS checked. Supplementary Drosophila inter-areal analysis is structural comparison; human functional-connectivity result is within human data and cannot establish cross-species transfer.",
        }
    )
    record["risk_flags"] = ["animal_to_human_transfer_unvalidated"]
    record = migrate_record(record, checked_at=DATE)
    sections = {
        "авторы": "Article byline",
        "год": "Citation header: 24 January 2018",
        "издание": "Citation header: volume 9, article 346",
        "модальность": "Abstract; Results > The weighted stochastic blockmodel and connectome data sets",
        "задача": "Abstract and Introduction",
        "метод": "Results > The weighted stochastic blockmodel and connectome data sets; Methods > Weighted stochastic blockmodel",
        "датасет": "Methods > Connectome data sets; Data availability",
        "производительность": "Results > Functional relevance of the WSBM, Figure 5; Supplementary Note 1 boundary",
        "кросс_субъект": "Methods > Connectome data sets: comparative structural analysis, not predictive transfer",
        "ограничения": "Results > Connectome data sets and Functional relevance; Discussion",
        "evidence.species": "Abstract; Methods > Connectome data sets",
        "evidence.population": "Methods > Connectome data sets and Human connectome data set",
        "evidence.sample_size": "Methods > Connectome data sets: no common animal/participant denominator",
        "evidence.target_construct": "Abstract: graph communities rather than a pain or SCS construct",
        "evidence.target_label": "Results > Community morphospace and diversity index",
        "validation.split_unit": "Methods: no trained subject-level prediction task",
        "validation.cross_subject": "Methods: structural comparison is not a held-out-subject test",
        "validation.external_validation": "Results: no Drosophila-to-human held-out transfer",
        "validation.calibration": "Methods: no probability-calibration target",
        "validation.uncertainty": "Results: no transfer-model uncertainty estimate",
        "validation.notes": "Abstract; Results > Functional relevance; Methods > Connectome data sets",
    }
    for path, section in sections.items():
        item = record["field_resolution"][path]
        item["reason"] = (
            "Checked in the primary full text; structural comparison is not dynamic or clinical transfer."
        )
        item["locators"] = [{"url": URL, "locator": section}]
    record["field_resolution"]["evidence.sample_size"].update(
        {
            "state": "not_reported",
            "value": None,
            "reason": "The five heterogeneous connectome sources have no single overall participant denominator.",
        }
    )
    record["field_resolution"]["identifiers.pmid"]["locators"] = [
        {"url": "https://pubmed.ncbi.nlm.nih.gov/29367627/", "locator": "PMID and DOI"},
    ]
    atomic_write_json(PATH, record)
    print(f"Prepared {record['id']}: {PATH}")


if __name__ == "__main__":
    main()
