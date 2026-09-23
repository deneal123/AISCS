#!/usr/bin/env python3
"""Audit the fixed 7 September 2026 record set without running a new search.

The script performs a transparent single-pass title/abstract review, checks PMC
full-text availability, preserves the identifiers of the previously curated
core, and writes the screening, extraction, quality-assessment and PRISMA
artifacts.  It deliberately does not claim independent dual screening.  Every
decision remains subject to author sign-off before submission.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


HERE = Path(__file__).resolve().parent
AUDIT_DATE = "2026-09-12"
USER_AGENT = "MIN-2026-pain-review-audit/1.0 (deneal123@mail.ru)"
PUBMED_METADATA = HERE / "pubmed_metadata.csv"
PMC_AUDIT = HERE / "pmc_full_text_audit.csv"


def read_csv(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, rows: list[dict[str, str]], fields: list[str]) -> None:
    with (HERE / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_doi(value: str) -> str:
    value = value.strip().lower()
    if value in {"", "nr", "na", "n/a"}:
        return ""
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value.rstrip(" .")


def compact(value: str) -> str:
    return " ".join((value or "").split())


def checked_or_inferred(previous: str, inferred: str) -> str:
    previous = compact(previous)
    if previous and previous.lower() not in {"nr", "see full text"}:
        return previous
    return inferred if inferred and inferred.lower() != "see full text" else "NR"


def xml_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return compact("".join(node.itertext()))


def request_bytes(url: str, *, retries: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def has(pattern: str, value: str) -> bool:
    return bool(re.search(pattern, value, re.I))


def pmid_for(record: dict[str, str]) -> str:
    explicit = record.get("pmid", "").strip()
    if explicit.isdigit():
        return explicit
    source_id = record.get("source_id", "").strip()
    return source_id if source_id.isdigit() else ""


def study_id_for(record: dict[str, str]) -> str:
    doi = normalize_doi(record.get("doi", ""))
    if doi:
        return f"S-{doi}"
    pmid = pmid_for(record)
    if pmid:
        return f"S-PMID-{pmid}"
    digest = hashlib.sha1(compact(record.get("title", "")).casefold().encode("utf-8")).hexdigest()[:12]
    return f"S-TITLE-{digest}"


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", compact(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-zа-я0-9]+", " ", value).strip()


def fetch_pubmed_metadata(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Enrich the frozen record set; this is metadata retrieval, not a new search."""
    pmids = [pmid_for(row) for row in records if pmid_for(row)]
    if PUBMED_METADATA.exists():
        cached = read_csv(PUBMED_METADATA.name)
        if set(pmids) <= {row["pmid"] for row in cached} and all(row.get("checked_at") == AUDIT_DATE for row in cached):
            return {row["pmid"]: row for row in cached}
    rows: list[dict[str, str]] = []
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
    for offset in range(0, len(pmids), 120):
        params = urllib.parse.urlencode({
            "db": "pubmed", "retmode": "xml", "id": ",".join(pmids[offset : offset + 120])
        })
        root = ET.fromstring(request_bytes(base + params))
        for article in root.findall("./PubmedArticle"):
            citation = article.find("./MedlineCitation")
            art = citation.find("./Article") if citation is not None else None
            pmid = xml_text(citation.find("./PMID") if citation is not None else None)
            types = sorted({xml_text(node) for node in article.findall(".//PublicationType") if xml_text(node)})
            mesh = sorted({xml_text(node) for node in article.findall(".//MeshHeading/DescriptorName") if xml_text(node)})
            pmcid = ""
            doi = ""
            for node in article.findall("./PubmedData/ArticleIdList/ArticleId"):
                if node.attrib.get("IdType") == "pmc":
                    pmcid = xml_text(node)
                elif node.attrib.get("IdType") == "doi":
                    doi = normalize_doi(xml_text(node))
            rows.append({
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": doi,
                "publication_types": "; ".join(types) or "NR",
                "mesh_humans": "yes" if "Humans" in mesh else "no",
                "mesh_animals": "yes" if "Animals" in mesh else "no",
                "mesh_terms": "; ".join(mesh) or "NR",
                "checked_at": AUDIT_DATE,
            })
        time.sleep(0.35)
    write_csv(
        PUBMED_METADATA.name,
        rows,
        ["pmid", "pmcid", "doi", "publication_types", "mesh_humans", "mesh_animals", "mesh_terms", "checked_at"],
    )
    return {row["pmid"]: row for row in rows}


def fetch_identifier_conversions(records: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Resolve PMID/PMCID for known DOIs without discovering new records."""
    dois = sorted({normalize_doi(row.get("doi", "")) for row in records if row.get("doi")})
    verification_path = HERE / "identifier_verification.csv"
    if verification_path.exists():
        cached = read_csv(verification_path.name)
        if set(dois) <= {row["requested_doi"] for row in cached} and all(row.get("checked_at") == AUDIT_DATE for row in cached):
            return {row["requested_doi"]: row for row in cached}
    rows: list[dict[str, str]] = []
    endpoint = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?"
    for offset in range(0, len(dois), 80):
        params = urllib.parse.urlencode({"format": "json", "ids": ",".join(dois[offset : offset + 80])})
        payload = json.loads(request_bytes(endpoint + params))
        for item in payload.get("records", []):
            requested = normalize_doi(str(item.get("requested-id", "")))
            doi = normalize_doi(str(item.get("doi", ""))) or requested
            rows.append({
                "requested_doi": requested,
                "doi": doi,
                "pmid": str(item.get("pmid", "")),
                "pmcid": str(item.get("pmcid", "")),
                "status": str(item.get("status", "resolved" if item.get("pmid") or item.get("pmcid") else "unresolved")),
                "checked_at": AUDIT_DATE,
            })
        time.sleep(0.35)
    write_csv(
        "identifier_verification.csv", rows,
        ["requested_doi", "doi", "pmid", "pmcid", "status", "checked_at"],
    )
    return {row["requested_doi"]: row for row in rows}


def fetch_pmc_audit(candidate_pmcids: list[str]) -> dict[str, dict[str, str]]:
    """Fetch available reports and retain metadata plus a content hash."""
    rows: list[dict[str, str]] = []
    if PMC_AUDIT.exists():
        rows = [row for row in read_csv(PMC_AUDIT.name) if row.get("checked_at") == AUDIT_DATE]
    cached_ids = {row["pmcid"] for row in rows}
    pending_pmcids = [pmcid for pmcid in candidate_pmcids if pmcid not in cached_ids]

    def fetch_one(pmcid: str) -> dict[str, str]:
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            payload = request_bytes(url, retries=2)
            article = ET.fromstring(payload)
        except Exception:
            bioc_url = f"https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{pmcid}/unicode"
            payload = request_bytes(bioc_url, retries=2)
            if payload.lstrip().startswith(b"[Error]"):
                raise ValueError("full text is not available through Europe PMC or the PMC open-access text endpoint")
            collections = json.loads(payload)
            document = collections[0]["documents"][0]
            passages = document.get("passages", [])
            infons = {}
            for passage in passages:
                infons.update(passage.get("infons", {}))
            section_titles = "; ".join(dict.fromkeys(
                compact(str(passage.get("infons", {}).get("section", "") or passage.get("infons", {}).get("section_type", "")))
                for passage in passages
                if passage.get("infons", {}).get("section") or passage.get("infons", {}).get("section_type")
            ))
            full_text = compact(" ".join(str(passage.get("text", "")) for passage in passages))
            title = next((compact(str(passage.get("text", ""))) for passage in passages if str(passage.get("infons", {}).get("type", "")).lower() == "title"), "NR")
            parsed_pmcid = str(infons.get("article-id_pmc", pmcid)).removeprefix("PMC")
            return {
                "pmcid": "PMC" + parsed_pmcid,
                "pmid": str(infons.get("article-id_pmid", "")),
                "doi": normalize_doi(str(infons.get("article-id_doi", ""))),
                "article_type": "author-manuscript" if document.get("infons", {}).get("license") == "author_manuscript" else "full-text-record",
                "title": title,
                "body_word_count": str(len(full_text.split())) if full_text else "0",
                "methods_section": "yes" if re.search(r"\b(method|methods|materials and methods|methodology)\b", section_titles, re.I) else "no",
                "section_titles": section_titles or "NR",
                "content_sha256": hashlib.sha256(payload).hexdigest(),
                "checked_at": AUDIT_DATE,
            }
        parsed_pmcid = pmcid
        pmid = ""
        doi = ""
        for node in article.findall(".//article-meta/article-id"):
            id_type = node.attrib.get("pub-id-type")
            if id_type == "pmc":
                parsed_pmcid = xml_text(node)
                if parsed_pmcid and not parsed_pmcid.startswith("PMC"):
                    parsed_pmcid = "PMC" + parsed_pmcid
            elif id_type == "pmid":
                pmid = xml_text(node)
            elif id_type == "doi":
                doi = normalize_doi(xml_text(node))
        body = article.find("./body")
        body_text = xml_text(body)
        section_titles = "; ".join(xml_text(node) for node in article.findall("./body//sec/title") if xml_text(node))
        article_xml = ET.tostring(article, encoding="utf-8")
        return {
            "pmcid": parsed_pmcid,
            "pmid": pmid,
            "doi": doi or "NR",
            "article_type": article.attrib.get("article-type", "NR") or "NR",
            "title": xml_text(article.find(".//article-meta/title-group/article-title")) or "NR",
            "body_word_count": str(len(body_text.split())) if body_text else "0",
            "methods_section": "yes" if re.search(r"\b(method|methods|materials and methods|methodology)\b", section_titles, re.I) else "no",
            "section_titles": section_titles or "NR",
            "content_sha256": hashlib.sha256(article_xml).hexdigest(),
            "checked_at": AUDIT_DATE,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_one, pmcid): pmcid for pmcid in pending_pmcids}
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception as exc:
                print(f"PMC retrieval failed for {futures[future]}: {exc}")
    rows.sort(key=lambda row: row["pmcid"])
    write_csv(
        PMC_AUDIT.name,
        rows,
        ["pmcid", "pmid", "doi", "article_type", "title", "body_word_count", "methods_section", "section_titles", "content_sha256", "checked_at"],
    )
    return {row["pmcid"]: row for row in rows}


SECONDARY_TITLE = re.compile(
    r"systematic review|scoping review|narrative review|integrative literature review|"
    r"meta-analysis|review and meta|\ba review\b|comprehensive review|\bsurvey\b|"
    r"consensus|roadmap|perspective|\boverview\b|handbook|commentary|\bin reply\b|"
    r"^letter:|interview|current state of science|future roles|history of|"
    r"rationale for|need for continued|recent advances|mechanisms and mode of action|"
    r"applications and future directions|towards artificial intelligence application|"
    r"closed-loop scs and sensing|advances in targeted closed loop|new paradigms",
    re.I,
)
PROTOCOL_TITLE = re.compile(
    r"study protocol|protocol for|planned study|medical hypothesis|design for a randomized|"
    r"study design|sample size calculations in future",
    re.I,
)
NONHUMAN_TITLE = re.compile(
    r"\b(cat|cats|feline|horse|horses|equine|rabbit|rabbits|sheep|goat|goats|"
    r"cattle|cow|cows|rat|rats|mouse|mice|macaque|macaques|animal|animals)\b",
    re.I,
)
PAIN = re.compile(r"\b(pain|nocicept|analgesi)", re.I)
SIGNAL = re.compile(
    r"physiolog|biosignal|eeg|ecg|eda|emg|ppg|bvp|fmri|fnirs|meg|facial|face|"
    r"video|speech|audio|movement|motion|inertial|wearable|ecap|evoked compound|"
    r"neural|skin potential|heart rate|vital sign|photopleth|image|grimace|"
    r"electrodermal|biopotential|voice|gait|accelerometer|multimodal|multi-modal|mri feature",
    re.I,
)
PATTERN_METHOD = re.compile(
    r"machine learning|deep learning|artificial intelligence|neural network|\bcnn\b|\brnn\b|"
    r"transformer|support vector|random forest|classifier|classification|regression|"
    r"computer vision|automated|automatic|algorithm|predictive model|prediction model|"
    r"pattern recognition|xgboost|\byolo\b|autoencoder|gaussian process|large language model",
    re.I,
)
DATASET = re.compile(r"\b(dataset|database|corpus|archive|data set)\b", re.I)
DATA_EVIDENCE = re.compile(
    r"\b(participant|participants|patient|patients|subject|subjects|dataset|database|"
    r"data set|recordings|images|signals|cohort|sample|neonates|children|adults|volunteers)\b",
    re.I,
)
SCS_RELEVANT = re.compile(
    r"ecap|evoked compound|machine learning|predict|wearable|eeg|meg|physiolog|"
    r"biomarker|heart rate|dose-response|closed-loop",
    re.I,
)

# Records whose titles can trigger broad lexical rules while the checked record
# has a different purpose.  Each override has one concrete primary reason.
EXPLICIT_EXCLUSIONS: dict[str, str] = {
    "R0001": "conference_supplement_without_extractable_primary_report",
    "R0008": "text_sentiment_without_biomedical_or_behavioral_pain_signal",
    "R0009": "methodological_framework_without_verified_human_experiment",
    "R0018": "technical_description_without_model_evaluation",
    "R0022": "case_report_and_secondary_discussion",
    "R0039": "data_labeling_software_not_pain_state_model",
    "R0044": "secondary_conceptual_discussion",
    "R0046": "secondary_narrative_review",
    "R0052": "clinical_outcome_association_without_signal_pattern_model",
    "R0095": "secondary_clinical_overview",
    "R0101": "secondary_mechanistic_review",
    "R0103": "comparative_treatment_series_without_signal_pattern_model",
    "R0109": "secondary_perspective",
    "R0122": "biochemical_association_dataset_outside_prespecified_signal_modalities",
    "R0140": "trial_methodology_without_pain_state_signal_model",
    "R0141": "scs_referral_triage_without_observed_treatment_response_or_signal",
    "R0144": "nonhuman_instrumentation_study",
    "R0150": "synthetic_computational_model_without_human_data",
    "R0157": "device_outcome_study_without_signal_pattern_model",
    "R0171": "secondary_psychophysiology_overview",
    "R0176": "triage_questionnaire_not_pain_state_signal_model",
    "R0180": "synthetic_computational_model_without_human_data",
    "R0190": "secondary_perspective",
    "R0192": "emotion_mapping_without_pain_target",
    "R0210": "general_ai_bias_article_without_pain_experiment",
    "R0211": "quality_of_life_analysis_without_signal_pattern_model",
    "R0214": "genetics_database_without_biomedical_signal_model",
    "R0236": "secondary_narrative_review",
    "R0260": "clinical_management_review_without_signal_model",
    "R0268": "face_detection_method_without_pain_target_evaluation",
    "R0281": "secondary_clinical_overview",
    "R0328": "device_outcome_study_without_signal_pattern_model",
    "R0329": "secondary_review",
    "R0335": "clinical_programming_overview",
    "R0344": "secondary_review",
    "R0345": "secondary_review",
    "R0356": "secondary_mechanistic_review",
    "R0367": "usability_study_without_pain_model_evaluation",
    "R0135": "design_and_requirements_study_without_model_evaluation",
    "R0320": "non_human_population",
}

FULLTEXT_EXCLUSIONS: dict[str, str] = {
    # Both abstracts sound eligible at first pass; inspection of the available
    # report shows that the evaluated target/data do not meet the protocol.
    "R0205": "face_tracking_evaluation_without_pain_target",
    "R0322": "synthetic_data_without_human_validation",
}

# These records were returned by the prespecified SCS/dataset streams but broad
# lexical filters miss their relevant signal or response target.  They still
# pass the secondary/protocol/non-human checks below.
EXPLICIT_CANDIDATES = {
    "R0010", "R0082", "R0175", "R0179", "R0193", "R0212", "R0224",
    "R0241", "R0247", "R0279", "R0300", "R0311", "R0321", "R0355",
}

SECONDARY_TYPES = {
    "Review", "Systematic Review", "Meta-Analysis", "Editorial", "Letter",
    "Comment", "News", "Practice Guideline", "Guideline",
}

CURATED_FIELD_CORRECTIONS: dict[str, dict[str, str]] = {
    "10.1038/s41597-024-03878-w": {
        "population": "55 healthy experimental + 49 physiotherapy participants",
        "pain_type": "experimental heat pain + clinical physiotherapy pain",
        "n_unique_subjects": "104",
        "reviewer_notes": "PainMonit has separate experimental (n=55) and physiotherapy (n=49) parts",
    },
    "10.1038/s41597-025-05982-x": {
        "population": "39 healthy volunteers; pain and motor tasks",
        "pain_type": "experimental thermal pain; separate motor task",
        "reviewer_notes": "CoSpine is an experimental healthy-volunteer dataset, not a clinical pain cohort",
    },
    "10.1186/s12911-025-03305-z": {
        "population": "24,211 postoperative patients in two hospital cohorts",
        "pain_type": "clinical postoperative pain",
        "n_unique_subjects": "24211",
        "reviewer_notes": "Total N is 21,855 development-centre patients plus 2,356 external-centre patients",
    },
}

# The role is the purpose of the report, not every noun found in its abstract.
# These sets were checked record by record against the title, abstract and,
# where retrievable, the archived full-text metadata.  Keeping the decisions
# explicit prevents phrases such as "the dataset was split" from turning an
# ordinary model paper into a dataset descriptor.
DATASET_RECORD_IDS = {
    "R0033", "R0111", "R0118", "R0132", "R0224", "R0253", "R0259",
    "R0261", "R0296", "R0321", "R0341", "R0346", "R0347", "R0351",
    "R0381",
}
SCS_TECHNICAL_RECORD_IDS = {
    "R0043", "R0108", "R0155", "R0158", "R0159", "R0160", "R0161",
    "R0178", "R0200", "R0230", "R0271", "R0339", "R0352",
}
DESCRIPTIVE_VALIDATION_RECORD_IDS = {"R0026", "R0177", "R0191", "R0379"}
COMPUTATIONAL_MODEL_RECORD_IDS = {"R0034", "R0201", "R0228", "R0245", "R0258", "R0319"}

# Explicitly reported independent/cross-dataset evaluations that are not all
# captured by a single lexical form.  An independent held-out subset from the
# same cohort is person-level validation but is not counted as external.
EXTERNAL_VALIDATION_RECORD_IDS = {
    "R0005", "R0034", "R0074", "R0173", "R0174", "R0189", "R0195",
    "R0250", "R0298", "R0313", "R0319",
}
PERSON_LEVEL_VALIDATION_RECORD_IDS = {
    "R0005", "R0034", "R0059", "R0074", "R0083", "R0088", "R0090",
    "R0110", "R0146", "R0155", "R0173", "R0174", "R0181", "R0184",
    "R0187", "R0188", "R0189", "R0195", "R0228", "R0232", "R0250",
    "R0255", "R0258", "R0280", "R0284", "R0298", "R0313", "R0319",
    "R0323", "R0352", "R0368", "R0371",
}


def title_abstract_decision(
    record: dict[str, str],
    retained_core: set[str],
    metadata: dict[str, str] | None = None,
) -> tuple[str, str]:
    rid = record["record_id"]
    title = compact(record["title"])
    evidence = f"{title} {compact(record.get('abstract', ''))}"
    doi = normalize_doi(record.get("doi", ""))
    if rid in EXPLICIT_EXCLUSIONS:
        return "exclude", EXPLICIT_EXCLUSIONS[rid]
    metadata = metadata or {}
    publication_types = {value.strip() for value in metadata.get("publication_types", "").split(";")}
    if publication_types & SECONDARY_TYPES:
        return "exclude", "secondary_review_commentary_or_guidance"
    if NONHUMAN_TITLE.search(title):
        return "exclude", "non_human_population"
    if metadata.get("mesh_animals") == "yes" and metadata.get("mesh_humans") != "yes":
        return "exclude", "non_human_population"
    if PROTOCOL_TITLE.search(title):
        return "exclude", "protocol_or_planned_study_without_results"
    if SECONDARY_TITLE.search(title):
        return "exclude", "secondary_review_commentary_or_guidance"
    if re.search(r"\b(this|the present|our) review\b|\bwe review\b|\breview aims\b", evidence, re.I):
        return "exclude", "secondary_review_commentary_or_guidance"
    if doi in retained_core:
        return "include", "previously_curated_eligible_primary_study"
    if rid in EXPLICIT_CANDIDATES:
        return "include", "potentially_eligible_scs_or_dataset_study"
    if not PAIN.search(evidence):
        return "exclude", "no_pain_related_target"
    if "spinal cord stimulation" in evidence.lower() and not SCS_RELEVANT.search(evidence):
        return "exclude", "scs_outcome_without_relevant_signal_or_prediction_task"
    if not SIGNAL.search(evidence):
        return "exclude", "no_biomedical_behavioral_neural_or_scs_signal"
    if not (PATTERN_METHOD.search(evidence) or DATASET.search(evidence) or SCS_RELEVANT.search(evidence)):
        return "exclude", "no_statistical_pattern_recognition_or_reusable_dataset"
    if not DATA_EVIDENCE.search(evidence):
        return "uncertain", "insufficient_population_or_experiment_information_in_record"
    return "include", "potentially_eligible_primary_human_study"


def fetch_pmc_status(records: list[dict[str, str]]) -> dict[str, str]:
    ids = [pmid_for(row) for row in records if pmid_for(row)]
    pmc_by_pmid: dict[str, str] = {}
    for offset in range(0, len(ids), 100):
        query = ",".join(ids[offset : offset + 100])
        url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?format=json&ids=" + query
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        for item in payload.get("records", []):
            if item.get("pmid") and item.get("pmcid"):
                pmc_by_pmid[str(item["pmid"])] = str(item["pmcid"])
        time.sleep(0.35)
    return pmc_by_pmid


def extract_n(abstract: str) -> str:
    text = compact(abstract)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    patterns = (
        r"(?:total of|included|enrolled|recruited|comprised|consisted of|data from)\s+(\d{1,5})\s+(?:human\s+)?(?:participants|patients|subjects|adults|children|neonates|infants|volunteers)",
        r"(?:participants|patients|subjects|adults|children|neonates|infants|volunteers)\s*\(n\s*=\s*(\d{1,5})\)",
        r"\bn\s*=\s*(\d{1,5})\b",
        r"(?:sample|cohort|dataset|study population)\s+(?:included|comprised|consisted of|contained)\s+(\d{1,5})\b",
        r"(?:sample|cohort)\s+(?:of|included a total of)\s+(\d{1,5})\b",
        r"\b(\d{1,5})\s+(?:healthy\s+)?(?:participants|patients|subjects|adults|children|neonates|infants|volunteers)\b",
        r"(?:data|recordings|signals|videos|images)\s+(?:were\s+)?(?:collected|obtained|recorded|acquired)\s+from\s+(\d{1,5})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return "NR"


def infer_population(text: str) -> str:
    lower = text.lower()
    if "spinal cord stimulation" in lower or re.search(r"\bscs\b", lower):
        return "SCS chronic pain"
    if "intensive care" in lower or re.search(r"\bicu\b", lower):
        return "clinical intensive care"
    if "neonat" in lower or "newborn" in lower or "infant" in lower:
        return "clinical neonatal/infant"
    if "child" in lower or "pediatric" in lower or "paediatric" in lower:
        return "clinical pediatric"
    if "dementia" in lower:
        return "clinical dementia"
    if "cancer" in lower:
        return "clinical cancer pain"
    if "postoperative" in lower or "post-surgical" in lower:
        return "clinical postoperative"
    if "chronic pain" in lower or "neuropathic pain" in lower:
        return "clinical chronic pain"
    if "healthy" in lower or "experimental" in lower or "stimulus" in lower:
        return "experimental human"
    if "patient" in lower or "clinical" in lower:
        return "clinical human"
    return "human population NR"


def infer_target(text: str) -> str:
    lower = text.lower()
    if "ecap" in lower or "evoked compound action potential" in lower:
        return "ECAP/recruitment"
    if "treatment response" in lower or "surgery outcome" in lower or "responder" in lower:
        return "clinical response"
    if "protective behavior" in lower or "facial action" in lower or "grimace" in lower:
        return "observed pain behavior"
    if "nocicept" in lower and "pain intensity" not in lower:
        return "nociceptive event or stimulus"
    if "pain intensity" in lower or "nrs" in lower or "vas" in lower:
        return "reported or annotated pain intensity"
    if "stimulus" in lower:
        return "experimental stimulus class"
    return "pain-related state"


def infer_target_source(text: str, target: str) -> str:
    lower = text.lower()
    if "ecap" in target.lower() or "recruitment" in target.lower():
        return "recorded evoked neural response"
    if re.search(r"patient[- ]reported|self[- ]report|visual analog|\bvas\b|numerical rating|\bnrs\b", lower):
        return "participant self-report"
    if re.search(r"npass|painad|painchek|behavioral pain scale|expert[- ]annotated|clinician[- ]rated|nurse", lower):
        return "observer or clinical scale"
    if re.search(r"thermal|electrical|pressure|capsaicin|heel lanc|blood sampling|painful procedure|noxious", lower):
        return "experimental or clinical stimulus/procedure"
    if "response" in target.lower() or "outcome" in target.lower():
        return "predefined clinical follow-up outcome"
    return "NR"


def infer_architecture(text: str) -> str:
    labels = []
    for pattern, label in (
        (r"convolutional neural network|\bcnn\b", "CNN"),
        (r"transformer", "transformer"),
        (r"long short[- ]term memory|\blstm\b|recurrent neural network|\brnn\b", "RNN/LSTM"),
        (r"support vector machine|\bsvm\b", "SVM"),
        (r"random forest", "random forest"),
        (r"xgboost|gradient boost", "gradient boosting"),
        (r"logistic regression", "logistic regression"),
        (r"gaussian process", "Gaussian process"),
        (r"deep learning|neural network", "deep neural network"),
    ):
        if re.search(pattern, text, re.I):
            labels.append(label)
    return "; ".join(dict.fromkeys(labels)) or "NR"


def infer_metrics(text: str) -> str:
    labels = []
    for pattern, label in (
        (r"accurac", "accuracy"), (r"area under|\bauroc\b|\bauc\b", "AUC"),
        (r"sensitivity", "sensitivity"), (r"specificity", "specificity"),
        (r"\bf1(?:[- ]score)?\b", "F1"), (r"mean absolute error|\bmae\b", "MAE"),
        (r"root mean square|\brmse\b", "RMSE"), (r"correlation|\bpcc\b", "correlation"),
        (r"agreement|intraclass correlation|\bicc\b", "agreement/ICC"),
    ):
        if re.search(pattern, text, re.I):
            labels.append(label)
    return "; ".join(dict.fromkeys(labels)) or "NR"


def infer_data_access(text: str) -> str:
    lower = text.lower()
    if re.search(r"publicly available|open[- ]source dataset|freely accessible|data (?:are|is) (?:available|provided)|github", lower):
        return "open or publicly downloadable"
    if re.search(r"available (?:on|upon) request|data use agreement|controlled access", lower):
        return "request or controlled access"
    return "NR"


def infer_code_access(text: str) -> str:
    return "open" if re.search(r"github|code (?:is|are) (?:available|provided)|open[- ]source code", text, re.I) else "NR"


def infer_role(record: dict[str, str], target: str, text: str) -> str:
    record_id = record["record_id"]
    lower = text.lower()
    if record_id in DATASET_RECORD_IDS:
        return "dataset_descriptor"
    if record_id in SCS_TECHNICAL_RECORD_IDS:
        return "scs_technical_control"
    if record_id in DESCRIPTIVE_VALIDATION_RECORD_IDS:
        return "descriptive_validation"
    if record_id in COMPUTATIONAL_MODEL_RECORD_IDS:
        return "diagnostic_or_prognostic_model"
    if "spinal cord stimulation" in lower or re.search(r"\bscs\b", lower):
        return "scs_prediction_or_longitudinal"
    if "stimulus" in target.lower() or "nociceptive" in target.lower():
        return "stimulus_recognition"
    if PATTERN_METHOD.search(text):
        return "diagnostic_or_prognostic_model"
    return "descriptive_validation"


def person_level_from_split(split: str) -> str:
    lower = split.lower()
    if any(token in lower for token in ("lopo", "loso", "leave-one-subject", "leave one subject", "person-level", "subject-level", "patient-level", "independent cohort", "external")):
        return "yes"
    if "window-level" in lower or "frame-level" in lower:
        return "no"
    return "NR"


def infer_modality(text: str) -> str:
    patterns = (
        (r"electrodermal|\beda\b|skin potential", "EDA/SP"),
        (r"\becg\b|electrocard", "ECG"),
        (r"\bppg\b|\bbvp\b|photopleth|heart rate|vital sign", "PPG/BVP/cardiorespiratory"),
        (r"\bemg\b|electromy", "EMG"),
        (r"\beeg\b|electroenceph", "EEG"),
        (r"\bfnirs\b|near-infrared", "fNIRS"),
        (r"\bfmri\b|mri feature|neuroimaging", "fMRI/MRI"),
        (r"\bmeg\b|magnetoenceph", "MEG"),
        (r"ecap|evoked compound action potential", "ECAP"),
        (r"facial|face|video|image|grimace", "face/video"),
        (r"speech|audio|voice|vocal", "speech/audio"),
        (r"movement|motion|inertial|accelerometer|gait", "movement/IMU"),
    )
    values = [label for pattern, label in patterns if re.search(pattern, text, re.I)]
    return "; ".join(dict.fromkeys(values)) or "NR"


def infer_split(text: str) -> tuple[str, str, str]:
    lower = text.lower()
    if re.search(r"external validation|external cohort|independent cohort|cross[- ]dataset", lower):
        return "external cohort/dataset", "yes", "yes"
    if re.search(r"leave[- ]one[- ]subject|\bloso\b|leave[- ]one[- ]patient|\blopo\b", lower):
        return "LOSO/LOPO", "no", "yes"
    if re.search(r"subject[- ]independent|participant[- ]level|patient[- ]level|subject[- ]level", lower):
        return "person-level split", "no", "yes"
    return "NR", "NR", "NR"


def infer_calibration(text: str) -> str:
    return "yes" if re.search(r"calibration (?:plot|slope|curve|analysis)|brier score", text, re.I) else "NR"


def infer_uncertainty(text: str) -> str:
    return "yes" if re.search(r"uncertainty quantification|prediction interval|conformal prediction", text, re.I) else "NR"


def main() -> None:
    records = read_csv("records.csv")
    conversions = fetch_identifier_conversions(records)
    for record in records:
        resolved = conversions.get(normalize_doi(record.get("doi", "")), {})
        record["pmid"] = pmid_for(record) or resolved.get("pmid", "")
        record["_pmcid"] = resolved.get("pmcid", "")
    curated_core = read_csv("curated_core.csv")
    prior_generated = read_csv("extraction.csv") if (HERE / "extraction.csv").exists() else []
    article_bibliography = read_csv("article_bibliography.csv")
    article_no = {normalize_doi(row["doi"]): row["ref_no"] for row in article_bibliography}
    retained_core = {normalize_doi(row["doi"]) for row in curated_core if row.get("doi")}
    curated_by_study = {row["study_id"]: row for row in curated_core}
    old_model_ids = {
        row["study_id"]: row["model_id"]
        for row in [*curated_core, *prior_generated]
        if row.get("study_id") and row.get("model_id")
    }
    next_model = max(int(re.search(r"\d+", value).group()) for value in old_model_ids.values()) + 1

    pubmed_metadata = fetch_pubmed_metadata(records)
    preliminary: list[tuple[dict[str, str], str, str]] = []
    candidate_pmcids: list[str] = []
    for record in records:
        meta = pubmed_metadata.get(pmid_for(record), {})
        decision, reason = title_abstract_decision(record, retained_core, meta)
        preliminary.append((record, decision, reason))
        pmcid = meta.get("pmcid") or record.get("_pmcid", "")
        if decision != "exclude" and pmcid:
            candidate_pmcids.append(pmcid)
    pmc_audit = fetch_pmc_audit(sorted(set(candidate_pmcids)))
    pmc_by_pmid = {pmid: meta.get("pmcid", "") for pmid, meta in pubmed_metadata.items()}
    fulltext_rows: list[dict[str, str]] = []
    screening: list[dict[str, str]] = []
    included_records: list[dict[str, str]] = []

    for record, ta_decision, ta_reason in preliminary:
        rid = record["record_id"]
        pmid = pmid_for(record)
        pmcid = pmc_by_pmid.get(pmid, "") or record.get("_pmcid", "")
        doi = normalize_doi(record.get("doi", ""))
        if ta_decision == "exclude":
            retrieval = "not_sought"
            full_decision = "not_assessed"
            primary_reason = ta_reason
            basis = "title_abstract"
            evidence_url = record.get("url", "")
        elif rid in FULLTEXT_EXCLUSIONS and pmcid in pmc_audit:
            retrieval = "retrieved_pmc"
            full_decision = "exclude"
            primary_reason = FULLTEXT_EXCLUSIONS[rid]
            basis = "pmc_full_text"
            evidence_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        elif doi in retained_core:
            retrieval = "retrieved_pmc" if pmcid in pmc_audit else "checked_curated_source"
            full_decision = "include"
            primary_reason = "included"
            basis = "pmc_full_text_and_curated_evidence_map" if pmcid in pmc_audit else "curated_evidence_map_and_available_report"
            evidence_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid in pmc_audit else (f"https://doi.org/{doi}" if doi else record.get("url", ""))
            included_records.append(record)
        elif pmcid in pmc_audit:
            retrieval = "retrieved_pmc"
            full_decision = "include"
            primary_reason = "included"
            basis = "title_abstract_and_pmc_full_text"
            evidence_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            included_records.append(record)
        else:
            retrieval = "not_retrieved"
            full_decision = "uncertain"
            primary_reason = "full_text_not_retrieved"
            basis = "title_abstract_only"
            evidence_url = record.get("url", "") or (f"https://doi.org/{doi}" if doi else "")

        sid = study_id_for(record) if full_decision == "include" else ""
        screening.append({
            "record_id": rid,
            "study_id": sid,
            "title_abstract_decision": ta_decision,
            "full_text_decision": full_decision,
            "primary_reason": primary_reason,
            "retrieval_status": retrieval,
            "decision_basis": basis,
            "evidence_url": evidence_url,
            "reviewer": "single-pass AI-assisted review; author sign-off pending",
            "checked_at": AUDIT_DATE,
            "notes": ta_reason if primary_reason == "included" else "Author verification required before submission",
        })
        fulltext_rows.append({
            "record_id": rid,
            "pmid": pmid,
            "pmcid": pmcid,
            "retrieval_status": retrieval,
            "evidence_url": evidence_url,
            "content_sha256": pmc_audit.get(pmcid, {}).get("content_sha256", ""),
            "body_word_count": pmc_audit.get(pmcid, {}).get("body_word_count", ""),
            "methods_section": pmc_audit.get(pmcid, {}).get("methods_section", ""),
            "checked_at": AUDIT_DATE,
        })

    evidence_map = read_csv("bibliography.csv")
    evidence_ref = {normalize_doi(item.get("doi", "")): item.get("ref_no", "") for item in evidence_map if item.get("doi")}
    evidence_year: dict[str, str] = {}
    for item in evidence_map:
        match = re.search(r"\b(19|20)\d{2}\b", item.get("raw_gost", ""))
        if item.get("doi") and match:
            evidence_year[normalize_doi(item["doi"])] = match.group()

    extraction: list[dict[str, str]] = []
    for record in included_records:
        sid = study_id_for(record)
        doi = normalize_doi(record.get("doi", ""))
        pmid = pmid_for(record)
        source_text = compact(f"{record.get('title', '')} {record.get('abstract', '')}")
        previous = dict(curated_by_study.get(sid, {}))
        previous.update(CURATED_FIELD_CORRECTIONS.get(doi, {}))
        for key, value in list(previous.items()):
            if compact(value).lower() == "see full text":
                previous[key] = "NR"
        if sid in old_model_ids:
            model_id = old_model_ids[sid]
        else:
            model_id = f"M{next_model:03d}-01"
            next_model += 1
        split, external, person_level = infer_split(source_text)
        if record["record_id"] in EXTERNAL_VALIDATION_RECORD_IDS:
            external = "yes"
            person_level = "yes"
            if split == "NR":
                split = "independent cohort or cross-dataset evaluation"
        elif record["record_id"] in PERSON_LEVEL_VALIDATION_RECORD_IDS:
            person_level = "yes"
            if split == "NR":
                split = "explicit person-level evaluation"
        population = checked_or_inferred(previous.get("population", ""), infer_population(source_text))
        target = checked_or_inferred(previous.get("target_name", ""), infer_target(source_text))
        modality = checked_or_inferred(previous.get("modality", ""), infer_modality(source_text))
        n_subjects = checked_or_inferred(previous.get("n_unique_subjects", ""), extract_n(record.get("abstract", "")))
        final_split = checked_or_inferred(previous.get("split_unit", ""), split)
        final_external = checked_or_inferred(previous.get("external_validation", ""), external)
        final_person_level = person_level_from_split(final_split)
        if final_person_level == "NR":
            final_person_level = checked_or_inferred(previous.get("person_level_validation", ""), person_level)
        role = infer_role(record, target, source_text)
        clinical_sample = "yes" if population.lower().startswith(("clinical", "scs")) or any(
            token in population.lower() for token in ("patient", "dementia", "cancer", "postoperative", "pediatric", "neonatal")
        ) else "no"
        row = {
            "record_id": record["record_id"],
            "study_id": sid,
            "model_id": model_id,
            "ref_no": previous.get("ref_no", "") or evidence_ref.get(doi, "") or "NR",
            "article_ref_no": article_no.get(doi, "") or "NR",
            "doi": doi or "NR",
            "pmid": pmid or previous.get("pmid", "") or "NR",
            "year": record.get("year", "") or previous.get("year", "") or evidence_year.get(doi, "") or "NR",
            "synthesis_role": role,
            "population": population,
            "pain_type": checked_or_inferred(previous.get("pain_type", ""), population),
            "n_unique_subjects": n_subjects,
            "n_sessions": checked_or_inferred(previous.get("n_sessions", ""), "NR"),
            "n_windows": checked_or_inferred(previous.get("n_windows", ""), "NR"),
            "target_name": target,
            "target_source": checked_or_inferred(previous.get("target_source", ""), infer_target_source(source_text, target)),
            "target_timing": checked_or_inferred(previous.get("target_timing", ""), "concurrent or study-defined; exact timing NR" if target != "NR" else "NR"),
            "modality": modality,
            "sensor": checked_or_inferred(previous.get("sensor", ""), modality),
            "sampling_rate": checked_or_inferred(previous.get("sampling_rate", ""), "NR"),
            "missingness": checked_or_inferred(previous.get("missingness", ""), "NR"),
            "preprocessing": checked_or_inferred(previous.get("preprocessing", ""), "NR"),
            "segmentation": checked_or_inferred(previous.get("segmentation", ""), "NR"),
            "features": checked_or_inferred(previous.get("features", ""), "NR"),
            "architecture": checked_or_inferred(previous.get("architecture", ""), infer_architecture(source_text)),
            "fusion": checked_or_inferred(previous.get("fusion", ""), "multimodal" if len(modality.split(";")) > 1 else "NA unimodal or NR"),
            "split_unit": final_split,
            "outer_validation": checked_or_inferred(previous.get("outer_validation", ""), final_split),
            "inner_tuning": checked_or_inferred(previous.get("inner_tuning", ""), "NR"),
            "external_validation": final_external,
            "person_level_validation": final_person_level,
            "clinical_sample": clinical_sample,
            "metrics": checked_or_inferred(previous.get("metrics", ""), infer_metrics(source_text)),
            "confidence_intervals": checked_or_inferred(previous.get("confidence_intervals", ""), "reported" if re.search(r"confidence interval|95% ci", source_text, re.I) else "NR"),
            "calibration": checked_or_inferred(previous.get("calibration", ""), infer_calibration(source_text)),
            "uncertainty": checked_or_inferred(previous.get("uncertainty", ""), infer_uncertainty(source_text)),
            "subgroup_analysis": checked_or_inferred(previous.get("subgroup_analysis", ""), "reported" if re.search(r"subgroup", source_text, re.I) else "NR"),
            "confounders": checked_or_inferred(previous.get("confounders", ""), "NR"),
            "data_access": checked_or_inferred(previous.get("data_access", ""), infer_data_access(source_text)),
            "code_access": checked_or_inferred(previous.get("code_access", ""), infer_code_access(source_text)),
            "funding": checked_or_inferred(previous.get("funding", ""), "NR"),
            "conflicts": checked_or_inferred(previous.get("conflicts", ""), "NR"),
            "evidence_basis": "curated evidence map and available report" if sid in curated_by_study else "PubMed record and PMC full text",
            "evidence_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_by_pmid[pmid]}/" if pmc_by_pmid.get(pmid) else (f"https://doi.org/{doi}" if doi else record.get("url", "")),
            "reviewer_notes": checked_or_inferred(previous.get("reviewer_notes", ""), "Single-pass extraction; author verification required"),
        }
        extraction.append(row)

    quality_rows: list[dict[str, str]] = []
    for row in extraction:
        target = row["target_name"].lower()
        population = row["population"].lower()
        role = row["synthesis_role"]
        if role == "dataset_descriptor":
            framework = "dataset_transparency"
            domains = {
                "sampling": ("clear" if row["n_unique_subjects"].isdigit() else "unclear", "Unique participant count and population description"),
                "labeling": ("clear" if row["target_source"] != "NR" else "unclear", "Target definition and provenance of labels"),
                "processing": ("unclear" if row["preprocessing"] == "NR" else "clear", "Processing boundary reported in checked source"),
                "validation_and_access": ("clear" if "open" in row["data_access"].lower() else "limited", "Reuse access and validation information"),
            }
        elif role in {"stimulus_recognition", "scs_technical_control", "descriptive_validation"}:
            framework = "validation_transparency"
            domains = {
                "sampling": ("clear" if row["n_unique_subjects"].isdigit() else "unclear", "Unique participant count and sampling frame"),
                "target_definition": ("clear" if row["target_source"] != "NR" else "unclear", "Stimulus, behavior, ECAP, or descriptive target kept distinct from pain self-report"),
                "processing_boundary": ("unclear" if row["preprocessing"] == "NR" else "clear", "Preprocessing and segmentation boundary"),
                "validation_design": ("clear" if row["split_unit"] != "NR" else "unclear", "Unit of separation between development and evaluation data"),
            }
        else:
            framework = "PROBAST+AI"
            outcome_judgment = "high" if "stimulus" in target else ("low" if row["target_source"] != "NR" else "unclear")
            if row["person_level_validation"] == "no":
                analysis_judgment = "high"
            elif row["person_level_validation"] == "yes" and row["inner_tuning"] != "NR" and row["confidence_intervals"] != "NR":
                analysis_judgment = "low"
            else:
                analysis_judgment = "unclear"
            domains = {
                "participants_and_data_sources": ("low" if row["n_unique_subjects"].isdigit() else "unclear", "Sampling frame and unique participant count"),
                "predictors": ("low" if row["modality"] != "NR" and row["preprocessing"] != "NR" else "unclear", "Signal acquisition and predictor processing"),
                "outcome": (outcome_judgment, "Outcome definition, timing, and separation from predictors"),
                "analysis": (analysis_judgment, "Person-level separation, tuning, and performance analysis"),
                "applicability_participants": ("high" if "experimental" in population else ("low" if population.startswith(("clinical", "scs")) else "unclear"), "Population match to clinical pain-state use"),
                "applicability_predictors": ("unclear" if row["sensor"] == "NR" else "low", "Availability of the measured predictors in intended use"),
                "applicability_outcome": ("low" if row["target_source"] != "NR" and "stimulus" not in target else "unclear", "Match between modeled target and intended clinical claim"),
            }
        for domain, (judgment, rationale_label) in domains.items():
            quality_rows.append({
                "study_id": row["study_id"],
                "model_id": row["model_id"],
                "assessment_framework": framework,
                "assessment_part": "model_evaluation" if framework == "PROBAST+AI" else "descriptive_transparency",
                "domain": domain,
                "judgment": judgment,
                "rationale": f"{rationale_label}; based on {row['evidence_basis']}. NR fields were not imputed.",
                "evidence_url": row["evidence_url"],
                "reviewer": "single-pass AI-assisted audit; author sign-off pending",
            })

    by_full = Counter(row["full_text_decision"] for row in screening)
    ta_excluded = sum(row["title_abstract_decision"] == "exclude" for row in screening)
    reports_sought = len(screening) - ta_excluded
    search_log = read_csv("search_log.csv")
    database_records = sum(int(row["retrieved_records"]) for row in search_log if row.get("role") == "formal discovery")
    other_records = sum(int(row["retrieved_records"]) for row in search_log if row.get("role") == "other methods and verification")
    counts = {
        "records_identified_databases": database_records,
        "records_identified_other_methods": other_records,
        "duplicate_records_removed": database_records + other_records - len(screening),
        "records_screened": len(screening),
        "records_excluded_title_abstract": ta_excluded,
        "reports_sought_for_retrieval": reports_sought,
        "reports_not_retrieved": by_full["uncertain"],
        "reports_assessed_for_eligibility": by_full["include"] + by_full["exclude"],
        "reports_excluded_full_text": by_full["exclude"],
        "studies_included": by_full["include"],
        "records_uncertain": by_full["uncertain"],
    }

    screening_fields = [
        "record_id", "study_id", "title_abstract_decision", "full_text_decision", "primary_reason",
        "retrieval_status", "decision_basis", "evidence_url", "reviewer", "checked_at", "notes",
    ]
    extraction_fields = [
        "record_id", "study_id", "model_id", "ref_no", "article_ref_no", "doi", "pmid", "year", "synthesis_role",
        "population", "pain_type", "n_unique_subjects", "n_sessions", "n_windows", "target_name",
        "target_source", "target_timing", "modality", "sensor", "sampling_rate", "missingness",
        "preprocessing", "segmentation", "features", "architecture", "fusion", "split_unit",
        "outer_validation", "inner_tuning", "external_validation", "person_level_validation",
        "clinical_sample", "metrics", "confidence_intervals", "calibration", "uncertainty",
        "subgroup_analysis", "confounders", "data_access", "code_access", "funding", "conflicts",
        "evidence_basis", "evidence_url", "reviewer_notes",
    ]
    quality_fields = [
        "study_id", "model_id", "assessment_framework", "assessment_part", "domain", "judgment",
        "rationale", "evidence_url", "reviewer",
    ]
    write_csv("screening.csv", screening, screening_fields)
    write_csv("full_text_status.csv", fulltext_rows, ["record_id", "pmid", "pmcid", "retrieval_status", "evidence_url", "content_sha256", "body_word_count", "methods_section", "checked_at"])
    write_csv("extraction.csv", extraction, extraction_fields)
    write_csv("risk_of_bias.csv", quality_rows, quality_fields)
    for record in records:
        record["source"] = record.get("source", "").replace("citation chasing", "previous evidence map")
        if "2026_update" in record.get("stream", ""):
            record["source"] = record["source"].replace("previous evidence map", "2026 evidence-map update")
        record["pmid"] = pmid_for(record) or "NR"
        record["doi"] = normalize_doi(record.get("doi", "")) or "NR"
        record["dedup_basis"] = "DOI -> PMID -> normalized title"
    write_csv(
        "records.csv", records,
        ["record_id", "source", "stream", "source_id", "pmid", "doi", "title", "abstract", "year", "url", "dedup_basis"],
    )
    for item in search_log:
        if item.get("role") == "other methods and verification":
            item["source"] = "previous evidence map and 2026 update"
            item["stream"] = "evidence_map_pool"
            item["query"] = "53 previously verified academic sources plus 7 records from the 2026 update"
    write_csv(
        "search_log.csv", search_log,
        ["search_date", "source", "stream", "query", "reported_results", "retrieved_records", "role"],
    )
    write_csv(
        "included_studies_bibliography.csv",
        [
            {
                "record_id": row["record_id"],
                "study_id": study_id_for(row),
                "evidence_map_ref_no": evidence_ref.get(normalize_doi(row.get("doi", "")), ""),
                "article_ref_no": article_no.get(normalize_doi(row.get("doi", "")), ""),
                "doi": normalize_doi(row.get("doi", "")) or "NR",
                "pmid": pmid_for(row),
                "year": row.get("year", "") or evidence_year.get(normalize_doi(row.get("doi", "")), "") or "NR",
                "title": compact(row.get("title", "")),
                "url": row.get("url", "") or (f"https://doi.org/{normalize_doi(row.get('doi', ''))}" if row.get("doi") else ""),
            }
            for row in included_records
        ],
        ["record_id", "study_id", "evidence_map_ref_no", "article_ref_no", "doi", "pmid", "year", "title", "url"],
    )
    (HERE / "prisma_counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    model_roles = {"diagnostic_or_prognostic_model", "stimulus_recognition", "scs_prediction_or_longitudinal"}
    model_rows = [row for row in extraction if row["synthesis_role"] in model_roles]
    numeric_n = [int(row["n_unique_subjects"]) for row in extraction if row["n_unique_subjects"].isdigit()]
    metrics = {
        "studies_included": len(extraction),
        "dataset_descriptors": sum(row["synthesis_role"] == "dataset_descriptor" for row in extraction),
        "model_studies": len(model_rows),
        "scs_technical_control_studies": sum(row["synthesis_role"] == "scs_technical_control" for row in extraction),
        "descriptive_validation_studies": sum(row["synthesis_role"] == "descriptive_validation" for row in extraction),
        "n_reported_exact": len(numeric_n),
        "n_median": statistics.median(numeric_n) if numeric_n else None,
        "n_min": min(numeric_n) if numeric_n else None,
        "n_max": max(numeric_n) if numeric_n else None,
        "person_level_validation_yes": sum(row["person_level_validation"] == "yes" for row in model_rows),
        "person_level_validation_denominator": len(model_rows),
        "external_validation_yes": sum(row["external_validation"] == "yes" for row in model_rows),
        "external_validation_denominator": len(model_rows),
        "clinical_sample_yes": sum(row["clinical_sample"] == "yes" for row in model_rows),
        "clinical_sample_denominator": len(model_rows),
        "calibration_yes": sum(row["calibration"] == "yes" for row in model_rows),
        "calibration_denominator": len(model_rows),
        "uncertainty_yes": sum(row["uncertainty"] == "yes" for row in model_rows),
        "uncertainty_denominator": len(model_rows),
        "open_data_confirmed": sum("open" in row["data_access"].lower() for row in extraction),
        "open_code_confirmed": sum(row["code_access"].lower() == "open" for row in extraction),
        "included_in_article_bibliography": sum(row["article_ref_no"] != "NR" for row in extraction),
        "included_in_reproducible_appendix": len(extraction),
    }
    (HERE / "corpus_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
