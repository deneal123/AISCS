#!/usr/bin/env python3
"""Refresh public-index search results without overwriting expert decisions.

By default the script writes ``*.refresh`` candidates for inspection.  With
``--apply-records`` it updates only the raw search, search log, deduplicated
record registry and DOI verification.  It never writes screening.csv,
extraction.csv, risk_of_bias.csv, or prisma_counts.json.
"""

from __future__ import annotations

import csv
import argparse
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
MATERIALS = ROOT / "docs" / "ai" / "materialy-dlya-obzornoi-stati.md"
SEARCH_DATE = "2026-09-07"
DATE_RANGE = '("2010/01/01"[Date - Publication] : "2026/09/07"[Date - Publication])'

QUERIES = {
    "pain_ml": (
        '(("pain assessment"[Title/Abstract] OR "pain recognition"[Title/Abstract] '
        'OR "pain intensity estimation"[Title/Abstract] OR "automatic pain"[Title/Abstract] '
        'OR "automated pain"[Title/Abstract]) AND ("machine learning"[Title/Abstract] '
        'OR "deep learning"[Title/Abstract] OR "artificial intelligence"[Title/Abstract] '
        'OR "pattern recognition"[Title/Abstract] OR "neural network"[Title/Abstract]) '
        'AND (physiolog*[Title/Abstract] OR biosignal*[Title/Abstract] '
        'OR electrodermal[Title/Abstract] OR ECG[Title/Abstract] OR PPG[Title/Abstract] '
        'OR EMG[Title/Abstract] OR EEG[Title/Abstract] OR fMRI[Title/Abstract] '
        'OR wearable[Title/Abstract] OR facial[Title/Abstract] OR video[Title/Abstract] '
        'OR speech[Title/Abstract] OR movement[Title/Abstract] OR multimodal[Title/Abstract])) '
        f"AND {DATE_RANGE}"
    ),
    "scs": (
        '("spinal cord stimulation"[Title/Abstract] AND ("machine learning"[Title/Abstract] '
        'OR ECAP[Title/Abstract] OR "evoked compound action potential"[Title/Abstract] '
        'OR "closed-loop"[Title/Abstract] OR wearable[Title/Abstract] OR prediction[Title])) '
        f'AND humans[MeSH Terms] AND {DATE_RANGE}'
    ),
    "datasets": (
        '((pain[Title] OR nocicept*[Title]) AND (dataset[Title] OR database[Title] '
        'OR corpus[Title] OR benchmark[Title]) AND human*[Title/Abstract]) '
        f"AND {DATE_RANGE}"
    ),
}


def get(url: str, *, retries: int = 4) -> bytes:
    headers = {"User-Agent": "MIN-2026-pain-mapping-review/1.0 (deneal123@mail.ru)"}
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return r.read()
        except Exception:
            if attempt + 1 == retries:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join("".join(node.itertext()).split())


def normalize_doi(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value)
    return value.rstrip(" .")


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-zа-я0-9]+", " ", value).strip()


def parse_working_bibliography() -> list[dict[str, str]]:
    body = MATERIALS.read_text(encoding="utf-8")
    body = body.split("### 22.1. Основное конференционное ядро", 1)[1]
    body = body.split("### 22.3. Официальные веб-ресурсы", 1)[0]
    rows: list[dict[str, str]] = []
    for line in body.splitlines():
        m = re.match(r"^(\d+)\.\s+(.+)$", line)
        if not m or not 1 <= int(m.group(1)) <= 53:
            continue
        raw = m.group(2).strip()
        doi_m = re.search(r"DOI:\s*([^\s.]+(?:\.[^\s.]+)*)", raw, re.I)
        # Stop DOI at the next sentence marker used by the source document.
        doi = ""
        if doi_m:
            doi = normalize_doi(doi_m.group(1).split(".—")[0].split(". —")[0])
        url_m = re.search(r"URL:\s*(https?://\S+)", raw)
        rows.append({
            "ref_no": m.group(1),
            "raw_gost": raw,
            "doi": doi,
            "url": url_m.group(1).rstrip(".)") if url_m else "",
        })
    return rows


PRIMARY = {
    # ref_no: population, n, target, modality, split, external, calibration,
    # uncertainty, data access, risk, concise note
    12: ("acute healthy + chronic clinical", "52", "self-report/CoVAS and NRS", "EDA, ECG, BVP, EMG, respiration, temperature", "NA descriptor", "NA", "NA", "NA", "open/restricted terms", "NA descriptor", "PainMonit descriptor; PMCD usable N not reported"),
    13: ("acute healthy", "87", "stimulus class", "EDA, ECG, EMG, video", "NA descriptor", "NA", "NA", "NA", "features open; raw request", "NA descriptor", "BioVid Part A; extracted features report 85 subjects"),
    14: ("acute healthy", "134", "thermal/electrical stimulus", "RGB, depth, thermal, audio, EDA, ECG, EMG", "NA descriptor", "NA", "NA", "NA", "request", "NA descriptor", "X-ITE"),
    15: ("mixed pain groups", "93", "self-report/pain group", "EDA, BVP, temperature, EEG-derived features", "NA descriptor", "NA", "NA", "NA", "open", "NA descriptor", "PhysioPain; 99 recruited, 93 records after QC"),
    16: ("pediatric rheumatology", "42", "Wong-Baker score", "EDA, BVP, temperature, activity", "NA descriptor", "NA", "NA", "NA", "open", "NA descriptor", "RheumaPain; activity is a major confounder"),
    17: ("acute healthy", "51", "self-report 1-10", "speech/audio", "NA descriptor", "NA", "NA", "NA", "restricted DUA", "NA descriptor", "TAME; 7039 utterances, lexical leakage must be controlled"),
    18: ("clinical shoulder pain", "25", "FACS/PSPI", "face video", "NA descriptor", "NA", "NA", "NA", "request/EULA", "NA descriptor", "UNBC; 200 sequences"),
    19: ("chronic low-back pain + controls", "30", "protective behavior", "IMU, EMG, video", "NA descriptor", "NA", "NA", "NA", "request", "NA descriptor", "EmoPain movement subset"),
    20: ("chronic pain + controls", "18", "pain/worry/confidence and activity", "IMU", "NA descriptor", "NA", "NA", "NA", "request", "NA descriptor", "EmoPain@Home; 9+9 participants"),
    21: ("acute healthy", "20", "electrical stimulus class", "RGB, depth, thermal", "NA descriptor", "NA", "NA", "NA", "request/EULA", "NA descriptor", "MIntPAIN"),
    22: ("acute healthy", "39", "NRS intensity/unpleasantness", "brain-spinal fMRI, pulse, respiration", "NA descriptor", "NA", "NA", "NA", "open", "NA descriptor", "CoSpine pain cohort; motor cohort is separate"),
    23: ("surgery under anesthesia", "101", "nociceptive event", "ECG, EDA, drugs", "NA descriptor", "NA", "NA", "NA", "restricted DUA", "NA descriptor", "18582 min and 49878 annotated stimuli"),
    24: ("acute healthy", "90", "stimulus-derived pain intensity", "biopotential features", "window-level", "no", "no", "no", "features open", "high", "Window-level leakage risk"),
    25: ("acute healthy", "NR", "continuous pain intensity", "biophysiological channels", "personal calibration", "no", "NR", "no", "request", "unclear", "Personal transform is calibration, not zero-shot"),
    26: ("acute healthy", "87", "continuous pain intensity", "autonomic signals", "subject held-out NR", "no", "no", "no", "request", "unclear", "Conference study"),
    27: ("acute healthy", "85", "pain intensity", "physiological signals", "LOPO", "no", "NR", "no", "features open", "some concerns", "Normalization of held-out subject may be transductive"),
    28: ("acute healthy", "NR", "high-level acute pain", "wrist EDA", "subject-level NR", "no", "no", "no", "NR", "some concerns", "Wearable laboratory study; arousal is nonspecific"),
    29: ("acute healthy", "87", "pain intensity", "physiological signals", "subject-level NR", "no", "no", "yes", "request", "some concerns", "Prediction intervals on BioVid"),
    30: ("acute healthy", "114", "evoked pain", "fMRI", "independent cohorts", "yes", "no", "no", "controlled access", "some concerns", "Neurologic Pain Signature; not chronic-pain validation"),
    31: ("chronic pain", "4", "within-person pain state", "intracranial LFP", "within-person temporal", "no", "NR", "NR", "controlled access", "high applicability risk", "First-in-human; no population-level generalization"),
    32: ("SCS chronic pain", "NR", "ECAP/recruitment", "spinal ECAP", "NA physiology", "no", "NA", "NA", "NR", "some concerns", "ECAP is recruitment, not pain intensity"),
    33: ("SCS chronic back/leg pain", "134", "responder outcome", "ECAP-controlled SCS + PROM", "randomized trial", "no", "NA", "NA", "controlled", "some concerns", "EVOKE; industry funded"),
    34: ("SCS chronic pain", "151", "treatment response", "clinical variables", "nested CV", "no", "no", "no", "closed", "high", "No independent external validation"),
    35: ("SCS chronic pain", "15", "longitudinal self-reported pain", "wearable activity + NRS/PRO", "subject-level NR", "no", "NR", "NR", "closed", "high", "20 recruited, 15 modeled; separation unclear"),
    43: ("acute healthy", "87", "stimulus class", "physiological signals", "subject-level NR", "no", "no", "no", "request", "some concerns", "Transformer baseline on BioVid"),
    44: ("chronic low-back pain", "30", "protective behavior", "IMU, EMG", "LOSO", "no", "no", "no", "request", "some concerns", "Behavior is not subjective intensity"),
    45: ("acute healthy", "NR", "pain beyond nociception", "fMRI", "independent cohorts", "yes", "no", "no", "controlled access", "some concerns", "Cerebral contribution beyond nociception"),
    47: ("SCS chronic pain", "14", "perception/discomfort threshold", "ECAP", "patient-level association", "no", "NA", "NA", "closed", "high applicability risk", "Perception is not analgesia"),
    48: ("SCS chronic pain", "56", "ECAP features/recruitment", "ECAP, posture", "patient library", "no", "NA", "NA", "closed", "some concerns", "Posture and pulse width alter ECAP"),
    51: ("SCS chronic pain", ">600", "pain reduction association", "ECAP-derived dose + PROM", "pooled observational", "no", "no", "no", "closed", "high", "Association does not prove pain sensing"),
    52: ("SCS chronic pain", "17", "surgery outcome", "intraoperative EEG", "LOOCV", "no", "no", "no", "closed", "high", "Very small modeled sample"),
    53: ("SCS + chronic pain + controls", "75", "group/SCS response", "MEG", "patient-level CV", "no", "no", "no", "closed", "high", "Weak association with NRS in SCS group"),
}

NEW_2026 = [
    ("10.1016/j.jpain.2026.106416", "42600964", "External Validation of EEG-Based Machine Learning Models for Continuous Pain Prediction", "external validation", "NR", "continuous pain", "EEG", "external", "yes", "NR", "NR", "NR", "some concerns", "Recent external-validation study"),
    ("10.3390/s26103181", "42197989", "Multimodal Detection of Pain and Anticipation Anxiety from Ultra-Short Duration Wearable Sensors Measurements", "acute healthy", "NR", "pain vs anticipation anxiety", "wearable multimodal", "subject-level NR", "no", "NR", "NR", "open article", "some concerns", "Contextual negative class is a methodological strength"),
    ("10.3390/s26103020", "42197829", "Real-Time Pain Assessment from Electrodermal Activity Using Deep Learning", "acute healthy", "NR", "pain state", "EDA", "subject-level NR", "no", "NR", "NR", "open article", "some concerns", "EDA remains nonspecific"),
    ("10.3390/s26102947", "42197756", "Connectivity-Based Pain Recognition from fNIRS: Parsimonious Subject-Independent Classification", "acute healthy", "65", "three pain levels", "fNIRS", "LOSO", "no", "no", "no", "open article", "some concerns", "High-pain recall about 50 percent despite 69.6 percent accuracy"),
    ("10.1155/prm/5131891", "42029549", "Machine Learning and ECG-Derived Biomarkers for Objective Pain Assessment", "acute healthy", "NR", "CoVAS zero/nonzero and intensity", "ECG/HRV", "subject-level NR", "no", "NR", "no", "open article", "high claim risk", "Uses objective wording; external validation not reported in abstract"),
    ("10.1111/nicc.70478", "41983382", "Assessment of Pain Intensity Using Deep Learning Models in Non-Communicative Intensive Care Patients", "clinical ICU", "120", "expert-annotated facial pain severity", "facial images", "split unit NR", "no", "no", "no", "article", "high", "636 images; inter-rater kappa 0.16"),
    ("10.1088/2057-1976/ae34b4", "41499809", "Explainable AI for Pain Perception: Subject-Independent EEG Decoding", "acute healthy", "50", "low/high stimulus pain", "EEG", "LOSO", "no", "no", "no", "article", "some concerns", "Subject-independent but single dataset"),
]

# Original evidence-map numbers used by the 50-item article bibliography.
ARTICLE_SOURCE_NOS = (
    1, 2, 3, 4, 5, 6, 7, 37, 38, 41, 40,
    12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    24, 25, 26, 27, 28, 29, 43, 44, 30, 45, 31, 32, 33,
    34, 35, 47, 48, 51, 52, 53,
)


def pubmed_search(stream: str, query: str) -> tuple[list[dict[str, str]], int]:
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    params = urllib.parse.urlencode({"db": "pubmed", "retmode": "json", "retmax": 10000, "term": query})
    result = json.loads(get(base + "esearch.fcgi?" + params))
    ids = result["esearchresult"]["idlist"]
    records: list[dict[str, str]] = []
    for offset in range(0, len(ids), 150):
        chunk = ",".join(ids[offset : offset + 150])
        xml = ET.fromstring(get(base + "efetch.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "retmode": "xml", "id": chunk})))
        for article in xml.findall(".//PubmedArticle"):
            citation = article.find("./MedlineCitation")
            art = citation.find("./Article") if citation is not None else None
            pmid = text(citation.find("./PMID") if citation is not None else None)
            title = text(art.find("./ArticleTitle") if art is not None else None)
            abstract = " ".join(text(x) for x in art.findall("./Abstract/AbstractText")) if art is not None else ""
            year = text(art.find("./Journal/JournalIssue/PubDate/Year") if art is not None else None)
            if not year:
                medline_date = text(art.find("./Journal/JournalIssue/PubDate/MedlineDate") if art is not None else None)
                year_m = re.search(r"(20\d{2}|19\d{2})", medline_date)
                year = year_m.group(1) if year_m else ""
            doi = ""
            for aid in article.findall("./PubmedData/ArticleIdList/ArticleId"):
                if aid.attrib.get("IdType") == "doi":
                    doi = normalize_doi(text(aid))
            records.append({"source": "PubMed", "stream": stream, "source_id": pmid, "doi": doi, "title": title, "abstract": abstract, "year": year, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})
        time.sleep(0.12)
    return records, int(result["esearchresult"]["count"])


def classify_search_record(r: dict[str, str], primary_dois: set[str], context_dois: set[str]) -> tuple[str, str, str]:
    doi = normalize_doi(r.get("doi", ""))
    hay = f"{r.get('title', '')} {r.get('abstract', '')}".casefold()
    title = r.get("title", "").casefold()
    if doi in primary_dois:
        return "include", "full_text", "included_verified_evidence_map"
    if doi in context_dois:
        return "exclude", "title_abstract", "secondary_or_methodological_context"
    if re.search(r"\b(mouse|mice|rat|rats|rodent|equine|horse|cat|dog|fish|animal)\b", hay) and not re.search(r"\b(human|patient|participant|adult|infant|neonat)\b", hay):
        return "exclude", "title_abstract", "non_human"
    if re.search(r"\b(review|meta-analysis|bibliometric|guideline|protocol|editorial|commentary|survey)\b", title):
        return "exclude", "title_abstract", "secondary_or_protocol"
    if re.search(r"chest pain|postoperative pain|postsurgical pain|risk prediction|triage|diagnos", title) and not re.search(r"facial|biosignal|physiolog|eeg|ecg|eda|fMRI|fnirs|wearable|speech|video|ecap", hay, re.I):
        return "exclude", "title_abstract", "clinical_risk_or_diagnosis_not_pain_state_signal"
    strong = bool(re.search(r"pain (assessment|recognition|intensity estimation|state|detection)", hay))
    modality = bool(re.search(r"physiolog|biosignal|eeg|ecg|eda|electrodermal|emg|ppg|fMRI|fnirs|wearable|facial|video|speech|multimodal|ecap", hay, re.I))
    validation = bool(re.search(r"external validation|subject-independent|leave-one-subject|dataset|database|corpus|calibrat|uncertaint|spinal cord stimulation|ecap", hay))
    if strong and modality and validation:
        return "exclude", "full_text", "outside_predefined_core_or_insufficient_extractable_reporting"
    return "exclude", "title_abstract", "outside_bounded_target_data_validation_scope"


def crossref_metadata(doi: str) -> dict:
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")
    try:
        return json.loads(get(url))["message"]
    except Exception as exc:
        return {"DOI": doi, "verification_error": str(exc)}


def openalex_metadata(doi: str) -> dict:
    url = "https://api.openalex.org/works/https://doi.org/" + urllib.parse.quote(doi, safe="")
    try:
        return json.loads(get(url))
    except Exception as exc:
        return {"doi": doi, "verification_error": str(exc)}


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-records", action="store_true",
        help="replace only raw/search/record/DOI files after producing the refresh snapshot",
    )
    args = parser.parse_args()
    HERE.mkdir(parents=True, exist_ok=True)
    bibliography = parse_working_bibliography()
    by_no = {int(row["ref_no"]): row for row in bibliography}
    article_dois = {normalize_doi(by_no[number]["doi"]) for number in ARTICLE_SOURCE_NOS}
    article_dois.update(normalize_doi(row[0]) for row in NEW_2026)

    all_records: list[dict[str, str]] = []
    search_log: list[dict[str, str | int]] = []
    raw: dict[str, list[dict[str, str]]] = {}
    for stream, query in QUERIES.items():
        rows, count = pubmed_search(stream, query)
        raw[stream] = rows
        all_records.extend(rows)
        search_log.append({
            "search_date": SEARCH_DATE, "source": "PubMed", "stream": stream, "query": query,
            "reported_results": count, "retrieved_records": len(rows), "role": "formal discovery",
        })

    # This fixed pool predates the reproducible PubMed search.  No unsupported
    # claim of forward/backward citation chasing is made.
    for item in bibliography:
        all_records.append({
            "source": "previous evidence map", "stream": "seed_evidence_map",
            "source_id": f"seed-{item['ref_no']}", "pmid": "", "doi": item["doi"],
            "title": item["raw_gost"].split(" // ")[0], "abstract": "", "year": "", "url": item["url"],
        })
    for values in NEW_2026:
        doi, pmid, title = values[:3]
        all_records.append({
            "source": "2026 evidence-map update", "stream": "2026_update", "source_id": pmid,
            "pmid": pmid, "doi": doi, "title": title, "abstract": "", "year": "2026",
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    other_count = len(bibliography) + len(NEW_2026)
    search_log.append({
        "search_date": SEARCH_DATE, "source": "previous evidence map and 2026 update",
        "stream": "evidence_map_pool", "query": "53 previously verified academic sources plus 7 records from the 2026 update",
        "reported_results": other_count, "retrieved_records": other_count, "role": "other methods and verification",
    })
    search_log.append({
        "search_date": SEARCH_DATE, "source": "official dataset repositories", "stream": "datasets",
        "query": "PainMonit; BioVid; X-ITE; PhysioPain; RheumaPain; TAME; UNBC; EmoPain; EmoPain@Home; MIntPAIN; CoSpine; PhysioNet surgery",
        "reported_results": 12, "retrieved_records": 12, "role": "official repository verification",
    })

    existing = []
    if (HERE / "records.csv").exists():
        with (HERE / "records.csv").open(encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    old_ids: dict[str, set[str]] = {}
    for row in existing:
        keys = []
        doi = normalize_doi(row.get("doi", ""))
        pmid = row.get("pmid", "") or (row.get("source_id", "") if row.get("source_id", "").isdigit() else "")
        title = normalize_title(row.get("title", ""))
        if doi:
            keys.append(f"doi:{doi}")
        if pmid:
            keys.append(f"pmid:{pmid}")
        if title:
            keys.append(f"title:{title}")
        for key in keys:
            old_ids.setdefault(key, set()).add(row["record_id"])

    merged: list[dict[str, str]] = []
    doi_index: dict[str, int] = {}
    pmid_index: dict[str, int] = {}
    title_index: dict[str, int] = {}
    source_rows = len(all_records)
    for incoming in all_records:
        incoming = dict(incoming)
        incoming["doi"] = normalize_doi(incoming.get("doi", ""))
        incoming["pmid"] = incoming.get("pmid", "") or (incoming.get("source_id", "") if incoming.get("source_id", "").isdigit() else "")
        doi_key = incoming["doi"]
        pmid_key = incoming["pmid"]
        title_key = normalize_title(incoming.get("title", ""))
        index = doi_index.get(doi_key) if doi_key else None
        if index is None and pmid_key:
            index = pmid_index.get(pmid_key)
        if index is None and title_key:
            index = title_index.get(title_key)
        if index is None:
            index = len(merged)
            merged.append(incoming)
        else:
            current = merged[index]
            current["source"] = "; ".join(sorted(set(current["source"].split("; ") + incoming["source"].split("; "))))
            current["stream"] = "; ".join(sorted(set(current["stream"].split("; ") + incoming["stream"].split("; "))))
            for field in ("abstract", "title", "year", "url", "doi", "pmid", "source_id"):
                if len(incoming.get(field, "")) > len(current.get(field, "")):
                    current[field] = incoming[field]
        current = merged[index]
        if current.get("doi"):
            doi_index[current["doi"]] = index
        if current.get("pmid"):
            pmid_index[current["pmid"]] = index
        if title_key:
            title_index[title_key] = index

    max_id = max((int(row["record_id"][1:]) for row in existing if re.fullmatch(r"R\d+", row.get("record_id", ""))), default=0)
    for row in merged:
        keys = []
        if row.get("doi"):
            keys.append(f"doi:{row['doi']}")
        if row.get("pmid"):
            keys.append(f"pmid:{row['pmid']}")
        title_key = normalize_title(row.get("title", ""))
        if title_key:
            keys.append(f"title:{title_key}")
        candidates = sorted({rid for key in keys for rid in old_ids.get(key, set())})
        if candidates:
            row["record_id"] = candidates[0]
        else:
            max_id += 1
            row["record_id"] = f"R{max_id:04d}"
        row["dedup_basis"] = "DOI -> PMID -> normalized title"
    records = sorted(merged, key=lambda row: int(row["record_id"][1:]))

    verification = []
    for doi in sorted(article_dois):
        cr = crossref_metadata(doi)
        oa = openalex_metadata(doi)
        verification.append({
            "doi": doi, "crossref_title": (cr.get("title") or [""])[0],
            "crossref_year": str((((cr.get("published") or {}).get("date-parts") or [[""]])[0][0])),
            "openalex_id": oa.get("id", ""), "openalex_title": oa.get("title", ""),
            "verified_crossref": "yes" if cr.get("title") else "no",
            "verified_openalex": "yes" if oa.get("id") else "no",
        })
        time.sleep(0.06)

    suffix = "" if args.apply_records else ".refresh"
    (HERE / f"raw_pubmed{suffix}.json").write_text(
        json.dumps({"search_date": SEARCH_DATE, "queries": QUERIES, "records": raw}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (HERE / f"verification_raw{suffix}.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(HERE / f"search_log{suffix}.csv", search_log, ["search_date", "source", "stream", "query", "reported_results", "retrieved_records", "role"])
    write_csv(HERE / f"records{suffix}.csv", records, ["record_id", "source", "stream", "source_id", "pmid", "doi", "title", "abstract", "year", "url", "dedup_basis"])
    write_csv(HERE / f"doi_verification{suffix}.csv", verification, ["doi", "crossref_title", "crossref_year", "openalex_id", "openalex_title", "verified_crossref", "verified_openalex"])
    print(json.dumps({
        "mode": "applied" if args.apply_records else "review_snapshot",
        "source_rows": source_rows,
        "deduplicated_records": len(records),
        "duplicate_records_removed": source_rows - len(records),
        "curation_files_modified": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
