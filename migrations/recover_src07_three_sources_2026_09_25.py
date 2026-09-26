"""Recover three wrongly rejected 2026 records from primary repositories."""

# ruff: noqa: E501 -- preserve primary file/field locators and scientific boundaries.

import argparse
import json
from pathlib import Path

from service.completeness import completeness_summary
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"
UW = "https://digital.lib.washington.edu/researchworks/items/622bc2dc-af95-4861-bc13-a91cab65eac8"
UW_PDF = "https://digital.lib.washington.edu/bitstreams/72513a4e-85b8-48f2-a5c0-f2446d758fe3/download"
ACM = "https://api.crossref.org/works/10.1145%2F3812836.3814769"
ZENODO = "https://zenodo.org/api/records/18911337"
ZENODO_DOCX = "https://zenodo.org/api/records/18911337/files/Devadas_MousingProblem_Zenodo_March2026.docx/content"


def resolution(source: dict, path: str, value: object, reason: str, url: str, locator: str, state: str = "reported") -> None:
    source["field_resolution"][path].update({
        "state": state, "value": value, "reason": reason, "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    })


def set_field(source: dict, path: str, value: object, reason: str, url: str, locator: str, state: str = "reported") -> None:
    if "." in path:
        outer, inner = path.split(".", 1)
        source[outer][inner] = value
    else:
        source[path] = value
    resolution(source, path, value, reason, url, locator, state)


def recover_thesis(source: dict, nociception: dict) -> None:
    if source["validation"]["status"] != "rejected" or source["id"] != "S013":
        raise ValueError("Unexpected S013 starting state")
    source["validation"].update({
        "status": "verified_primary", "screening_status": "included_core",
        "full_text_status": "checked", "checked_at": DATE, "exclusion_reason": None,
        "notes": "University of Washington doctoral thesis and 124-page deposited PDF verified. Chapter 2 Results and Methods (printed pp. 19-59) describe adult abdominal md-neuron optogenetic escape/avoidance assays, calcium heat responses and manually proofread FANC/MANC connectomic analyses; methods tested 2-5-day-old adults separated by sex. Chapter 2 overlaps preprint S029 and is not independent replication. Behavioral aversion and neural response do not establish subjective pain; no human ECAP/SCS transfer tested.",
    })
    changes = {
        "авторы": ("Jones, Jessica Maia", UW, "citation_author"),
        "метод": ("Adult Drosophila abdominal md-neuron optogenetic quadrant and free-walking assays, calcium imaging, connectomic reconstruction of FANC/MANC and single-cell RNA sequencing", UW_PDF, "Abstract; Chapter 2 Results pp. 19-36 and Methods pp. 44-59"),
        "датасет": ("Adult Drosophila melanogaster abdominal multidendritic neurons; 2-5-day-old adults tested by sex; separate FANC/MANC/BANC connectomic specimens", UW_PDF, "Chapter 2 Methods pp. 51-59; connectome data resources and reconstruction"),
        "производительность": ("Chapter 2 reports md-neuron-evoked running/jumping and sustained avoidance, heat-evoked calcium responses and distinct downstream pathways; no prediction accuracy or human pain metric", UW_PDF, "Abstract; Chapter 2 Results pp. 19-36"),
        "ограничения": ("Doctoral thesis, with Chapter 2 overlapping S029. Fly nocifensive behavior and calcium signals are distinct observations and do not establish subjective pain or transfer to human ECAP/SCS outcomes. Exact FANC/MANC/BANC graph releases are not established by the inspected methods.", UW_PDF, "Chapter 2 Methods pp. 44-59 and thesis abstract"),
        "identifiers.exact_url": (UW, UW, "citation_title, citation_author, citation_publication_date, citation_pdf_url"),
        "evidence.species": ("Drosophila melanogaster", UW_PDF, "Abstract and Chapter 2 Methods"),
        "evidence.population": ("Adult flies, 2-5 days old in free-walking optogenetic assays, separated by sex", UW_PDF, "Chapter 2 Methods p. 51"),
        "evidence.target_construct": ("nociceptive_response", UW_PDF, "Chapter 2 Results: escape/avoidance and calcium response"),
        "evidence.target_label": ("Optogenetically evoked running/jumping and sustained avoidance, with separate heat-evoked calcium response", UW_PDF, "Chapter 2 Results pp. 19-36"),
        "validation.notes": (source["validation"]["notes"], UW_PDF, "Abstract; Chapter 2 Results pp. 19-36; Methods pp. 44-59"),
        "validation.checked_at": (DATE, UW_PDF, "Primary PDF inspected on 2026-09-25"),
    }
    for path, (value, url, locator) in changes.items():
        set_field(source, path, value, "Confirmed in the institutional dissertation record and inspected primary PDF.", url, locator)
    source["evidence"]["evidence_role"] = "simulation_foundation"
    resolution(source, "validation.exclusion_reason", None, "Identity and Chapter 2 method were verified; previous unverifiable exclusion is withdrawn.", UW_PDF, "Title page, abstract and Chapter 2 Methods", "not_applicable")
    source["risk_flags"] = ["animal_to_human_transfer_unvalidated", "missing_reported_metrics"]
    entry = next(item for item in nociception["entries"] if item["source_id"] == "S013")
    entry["primary_pdf_review"] = {
        "checked_at": DATE, "url": UW_PDF,
        "locators": ["Abstract pp. iii-iv", "Chapter 2 Results pp. 19-36", "Chapter 2 Methods pp. 44-59"],
        "boundary": "Adult fly stimulus, neural response and behavior are separate; thesis Chapter 2 overlaps S029 and does not independently measure subjective pain.",
    }


def recover_acm(source: dict) -> None:
    if source["validation"]["status"] != "rejected" or source["id"] != "S018":
        raise ValueError("Unexpected S018 starting state")
    source["validation"].update({
        "status": "verified_metadata", "screening_status": "included_context",
        "full_text_status": "metadata_only", "checked_at": DATE, "exclusion_reason": None,
        "notes": "ACM proceedings DOI and bibliographic record are verified, but the ACM article page returned HTTP 403 and no primary full method was obtained. Cohort, EEG features, pain target, split and metrics cannot be inferred from the title.",
    })
    changes = {
        "авторы": ("Mukhopadhyay, Shalini; Sarkar, Mayuk; Dey, Swarnava; Sinha, Aniruddha; Ghose, Avik", "message.author"),
        "издание": ("Proceedings of the 24th Annual International Conference on Mobile Systems, Applications and Services Workshops:130-135", "message.container-title, page"),
        "identifiers.doi": ("10.1145/3812836.3814769", "message.DOI"),
        "identifiers.exact_url": ("https://doi.org/10.1145/3812836.3814769", "message.DOI and resource.primary.URL"),
        "ограничения": (source["validation"]["notes"], "message.title, type, container-title, page; ACM full-text access checked separately"),
        "validation.notes": (source["validation"]["notes"], "message.title, type, author, published, page"),
        "validation.checked_at": (DATE, "message.DOI checked on 2026-09-25"),
    }
    for path, (value, locator) in changes.items():
        set_field(source, path, value, "Exact ACM proceedings DOI record confirms identity and edition, not methods.", ACM, locator)
    set_field(source, "метод", None, "Full method is inaccessible; 'ML' in the imported card was not independently established.", ACM, "DOI metadata only; ACM article URL returned HTTP 403", "not_reported")
    source["evidence"]["evidence_role"] = "context_only"
    resolution(source, "validation.exclusion_reason", None, "Exact DOI publication found, so previous unverifiable exclusion is withdrawn.", ACM, "message.DOI, title, author", "not_applicable")
    source["risk_flags"] = ["metadata_only", "claim_not_supported"]


def recover_position_paper(source: dict) -> None:
    if source["validation"]["status"] != "rejected" or source["id"] != "S233":
        raise ValueError("Unexpected S233 starting state")
    source["validation"].update({
        "status": "verified_primary", "screening_status": "included_context",
        "full_text_status": "checked", "checked_at": DATE, "exclusion_reason": None,
        "notes": "Zenodo DOI and open author DOCX were checked. The document calls itself a position paper and makes a narrative ethics argument about whole-brain emulation and AI suffering; it reports no new neural experiment, patient cohort or validated suffering metric. Claims about Eon and mouse experiments remain secondary interpretations.",
    })
    changes = {
        "название": ("The Mousing Problem: Why Whole-Brain Emulation Makes AI Suffering Measurable, and What Existing Neuroscience Already Tells Us About It", ZENODO, "metadata.title"),
        "авторы": ("Devadas, Ganesh Rajendra", ZENODO_DOCX, "Document title page; Zenodo metadata.creators[0] is Ganesh Devadas"),
        "издание": ("Zenodo preprint, 8 March 2026", ZENODO, "metadata.publication_date and resource_type.subtype=preprint"),
        "метод": ("Position paper and narrative ethical argument; no new experiment", ZENODO_DOCX, "Document heading and sections 1-4"),
        "производительность": (None, ZENODO_DOCX, "No experimental performance measure reported"),
        "ограничения": ("Self-deposited position paper, not peer reviewed; no new connectome simulation, animal experiment, human data or validated measure of subjective suffering. Third-party demonstrations and mouse studies are cited, not independently replicated.", ZENODO_DOCX, "Abstract, conclusion and references"),
        "identifiers.doi": ("10.5281/zenodo.18911337", ZENODO, "doi"),
        "identifiers.exact_url": ("https://zenodo.org/records/18911337", ZENODO, "id and links.self_html"),
        "evidence.target_construct": ("not_applicable", ZENODO_DOCX, "Position paper, no measured target"),
        "evidence.access_status": ("open", ZENODO, "files[0].links.self; open DOCX retrieved"),
        "validation.notes": (source["validation"]["notes"], ZENODO_DOCX, "Title page, abstract, conclusion and references"),
        "validation.checked_at": (DATE, ZENODO_DOCX, "Open author DOCX checked on 2026-09-25"),
    }
    for path, (value, url, locator) in changes.items():
        if path == "название":
            source[path] = value
            continue
        state = "not_applicable" if path == "производительность" else "reported"
        set_field(source, path, value, "Zenodo primary deposit and open author DOCX establish identity and non-empirical scope.", url, locator, state)
    source["evidence"].update({"evidence_role": "context_only", "modalities": []})
    resolution(source, "evidence.modalities", None, "No neural measurement was performed in this position paper.", ZENODO_DOCX, "Abstract and document sections", "not_applicable")
    resolution(source, "validation.exclusion_reason", None, "Stable DOI and primary author document found; previous unverifiable exclusion is withdrawn.", ZENODO, "doi and files", "not_applicable")
    source["risk_flags"] = ["claim_not_supported"]


def normalize_recovered_resolutions(source: dict) -> None:
    sid = source["id"]
    url = {"S013": UW_PDF, "S018": ACM, "S233": ZENODO_DOCX}[sid]
    source["provenance"].update({
        "retrieved_at": DATE,
        "search_stream": "SRC-07",
        "query_or_seed": source["название"],
        "iteration": "2026-09-25-primary-recovery",
    })
    for key in ("retrieved_at", "search_stream", "query_or_seed", "iteration"):
        value = source["provenance"][key]
        resolution(source, f"provenance.{key}", value, "Primary identity was rechecked in the 2026 version sweep.", url, "dated primary recovery audit")

    not_applicable = {
        "S013": {"identifiers.pmid", "identifiers.arxiv_id", "identifiers.patent_id", "identifiers.dataset_id"},
        "S018": {"identifiers.arxiv_id", "identifiers.patent_id", "identifiers.dataset_id"},
        "S233": {"identifiers.pmid", "identifiers.arxiv_id", "identifiers.patent_id", "identifiers.dataset_id", "evidence.species", "evidence.population", "evidence.subject_domain", "evidence.sample_size", "evidence.target_label"},
    }[sid]
    if sid == "S233":
        source["evidence"]["subject_domain"] = "not_applicable"
    for path, item in source["field_resolution"].items():
        if "rejected" not in item.get("reason", "") and "не выполняется" not in item.get("reason", ""):
            continue
        if path in not_applicable:
            state, reason = "not_applicable", "Field does not apply to this verified source type or evidence role."
        elif sid == "S013":
            state, reason = "not_reported", "The inspected institutional thesis record and bounded Chapter 2 review do not establish this optional identifier or aggregate sample count."
        elif sid == "S018":
            state, reason = "unavailable_after_search", "Exact DOI metadata are verified, but ACM full text returned HTTP 403 and this methodological field cannot be extracted from title or citation."
        else:
            state, reason = "not_applicable", "The open position paper does not report an empirical measure for this field."
        resolution(source, path, None, reason, url, "primary source identity and access review", state)


def updated() -> tuple[dict, dict, dict, dict]:
    records = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    nociception = json.loads((DATA / "drosophila-nociception-audit.json").read_text(encoding="utf-8"))
    by_id = {source["id"]: source for source in records["sources"]}
    recover_thesis(by_id["S013"], nociception)
    recover_acm(by_id["S018"])
    recover_position_paper(by_id["S233"])
    for sid in ("S013", "S018", "S233"):
        normalize_recovered_resolutions(by_id[sid])
    records["meta"]["verified_primary_count"] = sum(
        source["validation"]["status"] == "verified_primary"
        for source in records["sources"]
    )
    completeness = json.loads((DATA / "completeness-report.json").read_text(encoding="utf-8"))
    completeness.update(completeness_summary(records["sources"]))
    audit = {
        "meta": {"schema_version": "1.0.0", "checked_at": DATE, "status": "three_rejected_sources_recovered"},
        "entries": [
            {"source_id": "S013", "status": "verified_primary", "primary_urls": [UW, UW_PDF], "locator": "repository citation meta tags; PDF title page, Abstract, Chapter 2 Results pp. 19-36 and Methods pp. 44-59", "boundary": "Thesis Chapter 2 overlaps S029; adult nociceptive behavior is not subjective pain or human transfer."},
            {"source_id": "S018", "status": "verified_metadata", "primary_urls": [ACM], "locator": "Crossref message.DOI, title, author, container-title, page, published", "boundary": "ACM page HTTP 403; methods, cohort, outcome and split remain unverified."},
            {"source_id": "S233", "status": "verified_primary_context_only", "primary_urls": [ZENODO, ZENODO_DOCX], "locator": "Zenodo metadata.title, doi, creators, publication_date, resource_type, files; author DOCX title page, abstract and conclusion", "boundary": "Position paper, no new empirical simulation or suffering measurement."},
        ],
    }
    return records, completeness, nociception, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, completeness, nociception, audit = updated()
    if not args.apply:
        print("Dry run: S013, S018 and S233 identity/status corrections")
        return
    snapshot = snapshot_repository(DATA, label="pre-src07-three-source-recovery")
    atomic_write_json(DATA / "records.json", records)
    atomic_write_json(DATA / "completeness-report.json", completeness)
    atomic_write_json(DATA / "drosophila-nociception-audit.json", nociception)
    atomic_write_json(DATA / "src07-three-source-recovery-2026-09-25.json", audit)
    print(f"Recovered S013, S018 and S233; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
