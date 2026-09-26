"""One-time schema-2 migration and Drosophila x SCS novelty baseline.

The migration is deterministic and intentionally does not infer missing scientific facts.
Missing values become terminal resolutions with a dated reason and locator.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from service.completeness import RESOLVED_PATHS, completeness_summary, migrate_record
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-23"


def load(name: str) -> dict[str, Any]:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def source(
    source_id: str,
    title: str,
    authors: str,
    venue: str,
    *,
    doi: str,
    pmid: str | None,
    exact_url: str,
    subject_domain: str,
    modalities: list[str],
    target_construct: str,
    method: str,
    limitation: str,
    preprint: bool = False,
) -> dict[str, Any]:
    record = {
        "id": source_id,
        "название": title,
        "авторы": authors,
        "год": 2026,
        "издание": venue,
        "модальность": ", ".join(modalities),
        "задача": "Коннектомно-ограниченное моделирование динамики Drosophila",
        "метод": method,
        "датасет": "FlyWire/BANC or adult Drosophila VNC connectome",
        "производительность": None,
        "кросс_субъект": "not_applicable",
        "релевантность": 5,
        "ограничения": limitation,
        "тип_источника": "препринт" if preprint else "метод",
        "identifiers": {
            "doi": doi,
            "pmid": pmid,
            "arxiv_id": None,
            "patent_id": None,
            "dataset_id": None,
            "exact_url": exact_url,
        },
        "provenance": {
            "import_source": "novelty-search-2026-09-23",
            "retrieved_at": DATE,
            "search_stream": "drosophila-scs/frontier-refresh",
            "query_or_seed": title,
            "iteration": 1,
        },
        "evidence": {
            "species": "Drosophila melanogaster",
            "population": "adult Drosophila",
            "subject_domain": subject_domain,
            "modalities": modalities,
            "sample_size": None,
            "target_construct": target_construct,
            "target_label": "connectome-constrained neural dynamics",
            "access_status": "open",
            "evidence_role": "simulation_foundation",
        },
        "validation": {
            "status": "verified_primary",
            "screening_status": "included_core",
            "full_text_status": "checked",
            "checked_at": DATE,
            "split_unit": "not_applicable",
            "cross_subject": "not_applicable",
            "external_validation": "not_reported",
            "calibration": "not_reported",
            "uncertainty": "not_reported",
            "exclusion_reason": None,
            "notes": limitation,
        },
        "relations": [],
        "risk_flags": [
            "animal_to_human_transfer_unvalidated",
            *(["preprint"] if preprint else []),
        ],
    }
    return migrate_record(record, checked_at=DATE)


NEW_SOURCES = (
    source(
        "S738",
        "Distributed control circuits across a brain-and-cord connectome",
        "Alexander S Bates; Jasper S Phelps; Minsu Kim; Helen H Yang; Arie Matsliah; "
        "Zaki Ajabi; Eric Perlman; Kevin M Delgado; Mohammed Abdal Monium Osman; "
        "Christopher K Salmon; Jay Gager; Benjamin Silverman; Sophia Renauld; Farzaan "
        "Salman; Janki Patel; Matthew F Collie; Jingxuan Fan; Diego A Pacheco; Yunzhi "
        "Zhao; Wenyi Zhang; Laia Serratosa Capdevila; Ruairí J V Roberts; Eva J "
        "Munnelly; Nina Griggs; Helen Langley; Borja Moya-Llamas; Zuoyu Zhang; Ryan T "
        "Maloney; Szi-Chieh Yu; Amy R Sterling; Marissa Sorek; Krzysztof Kruk; Nikitas "
        "Serafetinidis; Serene Dhawan; Finja Klemm; Paul Brooks; Ellen Lesser; Jessica M "
        "Jones; Sara E Pierce-Lundgren; Su-Yee Lee; Yichen Luo; Andrew P Cook; Theresa H "
        "McKim; Dimitrios Stasi Giakoumas; Benjamin Gorko; Justin Ellis-Joyce; Jiayi "
        "Zhang; Emily C Kophs; Tjalda Falt; Alexa M Negron-Morales; Austin Burke; James "
        "Hebditch; Kyle P Willie; Ryan Willie; Sergiy Popovych; Nico Kemnitz; Dodam Ih; "
        "Kisuk Lee; Ran Lu; Akhilesh Halageri; J Alexander Bae; Ben Jourdan; Gregory "
        "Schwartzman; Damian D Demarest; Emily Behnke; Doug Bland; Anne Kristiansen; "
        "Jaime Skelton; Tom Stocks; Dustin Garner; Anthony Hernandez; Sandeep Kumar; "
        "BANC-FlyWire Consortium; Kevin C Daly; Sven Dorkenwald; Forrest Collman; Marie "
        "P Suver; Lisa M Fenk; Michael J Pankratz; Zepeng Yao; Fei Wang; Stephen J "
        "Huston; Tomke Stürner; Gregory S X E Jefferis; Katharina Eichler; Andrew M "
        "Seeds; Stefanie Hampel; Sweta Agrawal; Tatsuo S Okubo; Meet Zandawala; Thomas "
        "Macrina; Diane-Yayra Adjavon; Jan Funke; John C Tuthill; Anthony Azevedo; H "
        "Sebastian Seung; Benjamin L de Bivort; Mala Murthy; Jan Drugowitsch; Rachel I "
        "Wilson; Wei-Chung Allen Lee",
        "Nature",
        doi="10.1038/s41586-026-10735-w",
        pmid="42259917",
        exact_url="https://pubmed.ncbi.nlm.nih.gov/42259917/",
        subject_domain="drosophila_adult",
        modalities=["connectome", "neural_activity", "behavior"],
        target_construct="technical_signal_quality",
        method="Synapse-resolution reconstruction and analysis of an adult brain-and-cord connectome",
        limitation=(
            "The source supports Drosophila brain-and-cord circuit architecture. It does not "
            "model nociception, human spinal physiology, ECAP, or clinical SCS outcomes."
        ),
    ),
    source(
        "S739",
        "Connectome-constrained modeling identifies neurons and synapses that sustain spontaneous activity in Drosophila",
        "Qianzhu Li; Wenhao Ping; Ke Zhang; Chaoming Wang",
        "bioRxiv",
        doi="10.64898/2026.08.21.745055",
        pmid=None,
        exact_url="https://www.biorxiv.org/content/10.64898/2026.08.21.745055v1",
        subject_domain="drosophila_adult",
        modalities=["connectome", "neural_activity"],
        target_construct="technical_signal_quality",
        method="FlyWire-constrained whole-brain dynamical model fitted to calcium recordings",
        limitation=(
            "Preprint about spontaneous activity; no nociceptive task, ECAP observation model, "
            "human transfer, SCS programming, or independent reproduction is reported."
        ),
        preprint=True,
    ),
    source(
        "S740",
        "Connectome simulations identify a central pattern generator circuit for fly walking",
        "Sarah M Pugliese; Grant M Chou; Elliott T T Abe; Denis Turcu; Jackson K Lancaster; "
        "John C Tuthill; Bingni W Brunton",
        "bioRxiv",
        doi="10.1101/2025.09.12.675944",
        pmid="42094485",
        exact_url="https://pubmed.ncbi.nlm.nih.gov/42094485/",
        subject_domain="drosophila_adult",
        modalities=["connectome", "neural_activity", "behavior"],
        target_construct="protective_behavior",
        method="Dynamic VNC connectome simulation with optogenetic validation of a motor pathway",
        limitation=(
            "The work validates a locomotor circuit, not nociception, ECAP generation, human "
            "spinal equivalence, or SCS response prediction."
        ),
        preprint=True,
    ),
)


UNCLUSTERED_ASSIGNMENTS = {
    "S001": ["C20"], "S003": ["C11"], "S014": ["C42"], "S021": ["C20"],
    "S022": ["C11"], "S026": ["C06", "C14"], "S070": ["C02"],
    "S071": ["C02"], "S072": ["C03"], "S078": ["C20"], "S190": ["C03"],
    "S191": ["C03"], "S193": ["C03"], "S214": ["C54"], "S227": ["C32"],
    "S296": ["C54"], "S330": ["C47"], "S730": ["C35"], "S731": ["C54"],
    "S738": ["C06", "C18", "C54"], "S739": ["C18", "C54"],
    "S740": ["C18", "C54"],
}


def resolved(value: Any, *, state: str, reason: str, url: str, locator: str) -> dict[str, Any]:
    return {
        "state": state,
        "value": value if state == "reported" else None,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


def migrate_st(payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(payload)
    for category in payload.get("categories", []):
        for subcategory in category.get("подкатегории", []):
            for item in subcategory.get("ресурсы", []):
                url = item.get("ссылка") or "local:validation-log"
                status = item.get("статус_валидации")
                is_code = "github.com" in str(url).casefold()
                reported_access = status in {"verified_primary", "verified_metadata", "partially_verified"}
                item["technical_resolution"] = {
                    "version_or_commit": resolved(
                        None,
                        state="unavailable_after_search" if is_code else "not_applicable",
                        reason=(
                            "Landing page was checked, but no immutable release or commit was pinned."
                            if is_code else "Version pin is not applicable to this resource type."
                        ),
                        url=url,
                        locator="repository release/tag/commit metadata",
                    ),
                    "license": resolved(
                        None,
                        state="unavailable_after_search" if is_code else "not_applicable",
                        reason=(
                            "The prior validation pass did not record a verified license locator."
                            if is_code else "Software-license extraction is not applicable."
                        ),
                        url=url,
                        locator="license metadata",
                    ),
                    "data_access": resolved(
                        "primary page reachable" if reported_access else None,
                        state="reported" if reported_access else "unavailable_after_search",
                        reason=(
                            "The exact primary page was reached during the recorded validation pass."
                            if reported_access else "The resource was rejected or unavailable."
                        ),
                        url=url,
                        locator="validated resource URL",
                    ),
                    "reproducibility": resolved(
                        None,
                        state="unavailable_after_search" if is_code else "not_applicable",
                        reason=(
                            "Existence was checked, but execution-level reproduction was not performed."
                            if is_code else "Execution-level reproduction is not applicable."
                        ),
                        url=url,
                        locator="runtime/reproduction status",
                    ),
                }
    payload["meta"]["resource_schema_version"] = "2.0.0"
    payload["meta"]["версия"] = "2.0.0"
    payload["meta"]["дата_валидации"] = DATE
    payload["meta"]["статус_валидации"] = (
        "терминальные решения сохранены; execution-level проверка отделена от проверки существования"
    )
    return payload


def migrate_clusters(payload: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload = deepcopy(payload)
    by_cluster = {item["id"]: item for item in payload["clusters"]}
    for source_id, cluster_ids in UNCLUSTERED_ASSIGNMENTS.items():
        for cluster_id in cluster_ids:
            members = by_cluster[cluster_id]["состав_кластера"]
            if source_id not in members:
                members.append(source_id)
    for cluster in payload["clusters"]:
        cluster["состав_кластера"] = sorted(
            set(cluster["состав_кластера"]), key=lambda item: int(item[1:])
        )
        cluster["записей"] = len(cluster["состав_кластера"])
        representative_id = cluster["представитель"]["id"]
        cluster["представитель"] = deepcopy(records[representative_id])
        cluster["синтез"] = (
            f"Тематическая проекция «{cluster['тема']}» содержит {cluster['записей']} "
            "канонических источников. Кластер служит навигации; научные выводы разрешаются "
            "только через evidence matrix и первичные локаторы."
        )
        cluster["content_review"] = {
            "status": "reviewed_for_scope",
            "checked_at": DATE,
            "membership_rule": "Title, target construct, evidence role, and validated limitations.",
            "limitations": "Cluster membership is not independent evidence and carries no ranking.",
        }
    refs = [item for cluster in payload["clusters"] for item in cluster["состав_кластера"]]
    canonical = set(records)
    payload["unclustered_record_ids"] = sorted(
        canonical - set(refs), key=lambda item: int(item[1:])
    )
    payload["unclustered_decisions"] = {
        source_id: {
            "decision": "no_cluster_applicable",
            "checked_at": DATE,
            "reason": "Rejected source is retained for audit traceability and excluded from thematic evidence clusters.",
        }
        for source_id in payload["unclustered_record_ids"]
    }
    counts = Counter(refs)
    payload["multiple_membership"] = {
        source_id: count for source_id, count in sorted(counts.items()) if count > 1
    }
    payload["multiple_membership_rationale"] = {
        source_id: {
            "checked_at": DATE,
            "reason": "The source supports distinct thematic projections; membership is navigational, not duplicate evidence.",
            "cluster_ids": [
                cluster["id"]
                for cluster in payload["clusters"]
                if source_id in cluster["состав_кластера"]
            ],
        }
        for source_id in payload["multiple_membership"]
    }
    meta = payload["meta"]
    meta.update(
        {
            "schema_version": "2.0.0",
            "version": "drosophila_scs_scope_review",
            "records_count": len(records),
            "cluster_references_count": len(refs),
            "unique_clustered_records_count": len(set(refs)),
            "unclustered_records_count": len(payload["unclustered_record_ids"]),
            "multiple_membership_records_count": len(payload["multiple_membership"]),
            "validation_status": "content reviewed for Drosophila x SCS scope",
            "updated_at": DATE,
        }
    )
    return payload


def source_schema() -> dict[str, Any]:
    schema = load("source-record.schema.json")
    schema["title"] = "Aspa canonical research source record schema 2.0"
    schema["required"] = [*schema["required"], "field_resolution"]
    schema["properties"]["field_resolution"] = {
        "type": "object",
        "additionalProperties": {"$ref": "#/$defs/resolved"},
        "required": list(RESOLVED_PATHS),
    }
    schema["$defs"] = {
        "locator": {
            "type": "object",
            "additionalProperties": False,
            "required": ["url", "locator"],
            "properties": {
                "url": {"type": "string", "minLength": 1},
                "locator": {"type": "string", "minLength": 1},
            },
        },
        "resolved": {
            "type": "object",
            "additionalProperties": False,
            "required": ["state", "value", "reason", "checked_at", "locators"],
            "properties": {
                "state": {
                    "enum": [
                        "reported", "not_reported", "not_applicable", "unavailable_after_search"
                    ]
                },
                "value": {},
                "reason": {"type": "string", "minLength": 1},
                "checked_at": {"type": "string", "format": "date"},
                "locators": {
                    "type": "array", "minItems": 1, "items": {"$ref": "#/$defs/locator"}
                },
            },
        },
    }
    return schema


def migrate() -> dict[str, Any]:
    records = load("records.json")
    existing = {item["id"]: migrate_record(item, checked_at=DATE) for item in records["sources"]}
    s066 = existing["S066"]
    s066["evidence"].update(
        {
            "species": "Drosophila melanogaster",
            "population": "larvae",
            "subject_domain": "drosophila_larva",
            "access_status": "open",
            "target_label": "nocifensive rolling and sensory-neuron gain",
        }
    )
    s066["provenance"].update(
        {
            "retrieved_at": DATE,
            "search_stream": "drosophila-scs/frontier-refresh",
            "query_or_seed": s066["название"],
            "iteration": 1,
        }
    )
    s066["ограничения"] = (
        "Larval nociceptive sensitization only; no subjective pain, human transfer, ECAP, or SCS validation."
    )
    existing["S066"] = migrate_record(s066, checked_at=DATE)
    for item in NEW_SOURCES:
        if item["id"] in existing:
            raise RuntimeError(f"new source id collision: {item['id']}")
        existing[item["id"]] = item
    records["sources"] = sorted(existing.values(), key=lambda item: int(item["id"][1:]))
    statuses = Counter(item["validation"]["status"] for item in records["sources"])
    records["meta"].update(
        {
            "schema_version": "2.0.0",
            "version": "schema_2_terminal_resolution_drosophila_scs",
            "records_count": len(records["sources"]),
            "verified_primary_count": statuses["verified_primary"],
            "unverified_count": statuses["unverified"],
            "validation_status": "terminal field resolution complete; G0_REVISE",
            "updated_at": DATE,
        }
    )

    vocab = load("vocabularies.json")
    vocab["schema_version"] = "2.0.0"
    vocab["resolution_state"] = [
        "reported", "not_reported", "not_applicable", "unavailable_after_search"
    ]
    for name in ("target_construct", "access_status", "subject_domain", "split_unit", "assessment_result"):
        vocab[name] = [value for value in vocab[name] if value != "unknown"]
        if "unavailable_after_search" not in vocab[name]:
            vocab[name].append("unavailable_after_search")
    vocab["modality"] = [value for value in vocab["modality"] if value != "unknown"]

    clusters = migrate_clusters(load("clusters.json"), existing)
    resources = migrate_st(load("ST.json"))
    aliases = load("aliases.json")
    aliases["meta"]["schema_version"] = "2.0.0"
    aliases["meta"]["updated_at"] = DATE

    evidence = load("evidence-matrix.json")
    evidence["meta"].update(
        {
            "version": "2.0.0",
            "generated_at": DATE,
            "scope": "Drosophila x ECAP x SCS traceability",
        }
    )
    for row in evidence["rows"]:
        urls = [existing[source_id]["identifiers"]["exact_url"] for source_id in row["source_ids"]]
        row["locators"] = [
            {"source_id": source_id, "url": url or "local:validation-log", "locator": "validated evidence row"}
            for source_id, url in zip(row["source_ids"], urls, strict=True)
        ]
    evidence["rows"].extend(
        [
            {
                "batch_id": "frontier-refresh-2026-09-23",
                "claim": "An adult Drosophila brain-and-cord connectome provides a unified structural substrate for distributed sensorimotor control.",
                "target_variable": "connectome structure",
                "population_or_data": "adult Drosophila brain and ventral nerve cord",
                "source_ids": ["S738"],
                "verified_evidence": "PubMed and the open Nature record identify the adult brain-and-cord connectome and distributed control analysis.",
                "limitations": "No nociceptive, ECAP, human spinal, or SCS validation.",
                "permitted_conclusion": "Use as Drosophila structural foundation only.",
                "locators": [{"source_id": "S738", "url": existing["S738"]["identifiers"]["exact_url"], "locator": "abstract and bibliographic record"}],
            },
            {
                "batch_id": "frontier-refresh-2026-09-23",
                "claim": "A connectome-constrained whole-brain model can be fitted to Drosophila calcium activity and tested on held-out dynamics.",
                "target_variable": "spontaneous neural dynamics",
                "population_or_data": "adult FlyWire connectome and head-fixed calcium recordings",
                "source_ids": ["S739"],
                "verified_evidence": "The bioRxiv primary page reports the fitted model, held-out trace, and perturbation analysis.",
                "limitations": "Preprint; no nociception, ECAP observation model, human transfer, or SCS outcome.",
                "permitted_conclusion": "Use as simulation-method prior art, not as transfer evidence.",
                "locators": [{"source_id": "S739", "url": existing["S739"]["identifiers"]["exact_url"], "locator": "abstract, methods overview, and discussion"}],
            },
            {
                "batch_id": "frontier-refresh-2026-09-23",
                "claim": "Dynamic VNC connectome simulation can nominate a compact motor circuit and a pathway validated optogenetically.",
                "target_variable": "rhythmic leg motor activity",
                "population_or_data": "adult Drosophila VNC connectomes",
                "source_ids": ["S740"],
                "verified_evidence": "PubMed/PMC full text reports simulation pruning and experimental validation of DNb08-driven rhythmic movement.",
                "limitations": "Locomotor mechanism, not nociception or SCS.",
                "permitted_conclusion": "Use as a methodological precedent for connectome simulation plus biological validation.",
                "locators": [{"source_id": "S740", "url": existing["S740"]["identifiers"]["exact_url"], "locator": "abstract and full-text computational model"}],
            },
        ]
    )

    validation_log = load("validation-log.json")
    validation_log["meta"]["checked_at"] = DATE
    validation_log["meta"]["status"] = "schema_2_terminal_resolution_complete_G0_REVISE"
    validation_log.setdefault("searches", []).extend(
        [
            {
                "search_id": "NS-2026-09-23-01",
                "date": DATE,
                "stream": "Drosophila brain-and-cord frontier",
                "query": "Drosophila brain-and-cord connectome 2026",
                "urls_reviewed": ["https://pubmed.ncbi.nlm.nih.gov/42259917/"],
                "source_ids": ["S738"],
                "decision": "included_core",
            },
            {
                "search_id": "NS-2026-09-23-02",
                "date": DATE,
                "stream": "connectome-constrained dynamics frontier",
                "query": "connectome-constrained modeling Drosophila spontaneous activity",
                "urls_reviewed": ["https://www.biorxiv.org/content/10.64898/2026.08.21.745055v1"],
                "source_ids": ["S739"],
                "decision": "included_core_preprint",
            },
            {
                "search_id": "NS-2026-09-23-03",
                "date": DATE,
                "stream": "Drosophila VNC dynamic simulation",
                "query": "Drosophila VNC connectome dynamic simulation central pattern generator",
                "urls_reviewed": ["https://pubmed.ncbi.nlm.nih.gov/42094485/"],
                "source_ids": ["S740"],
                "decision": "included_core_preprint",
            },
        ]
    )

    report = completeness_summary(records["sources"])
    completeness = {
        "meta": {
            "schema_version": "1.0.0",
            "generated_at": DATE,
            "records_schema_version": "2.0.0",
            "gate": "G0_REVISE",
        },
        **report,
        "policy": {
            "forbidden": ["unknown", "empty string", "TODO", "TBD", "Не указано", "unexplained null"],
            "terminal_states": ["reported", "not_reported", "not_applicable", "unavailable_after_search"],
            "structural_null_exceptions": ["resolved.value for terminal states", "mutually exclusive relation target_id/external_id"],
        },
    }
    return {
        "records.json": records,
        "clusters.json": clusters,
        "ST.json": resources,
        "aliases.json": aliases,
        "vocabularies.json": vocab,
        "source-record.schema.json": source_schema(),
        "evidence-matrix.json": evidence,
        "validation-log.json": validation_log,
        "completeness-report.json": completeness,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = migrate()
    summary = {
        "ok": True,
        "apply": args.apply,
        "files": sorted(outputs),
        "records": len(outputs["records.json"]["sources"]),
        "unresolved": outputs["completeness-report.json"]["unresolved_count"],
    }
    if args.apply:
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
