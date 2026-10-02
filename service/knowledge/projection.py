"""Deterministic knowledge graph with document-scoped scientific entities."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from ..core import ResearchRepository, load_json
from ..data_layout import DATA_PATHS, data_path


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:24]


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def project(repository: ResearchRepository) -> dict:
    bundle = repository.bundle()
    nodes, edges = {}, {}

    def node(
        identity,
        kind,
        text,
        source_ids=None,
        metadata=None,
        locators=None,
        validation_status="verified",
        limitations="",
        permitted_conclusion="",
    ):
        if identity not in nodes:
            nodes[identity] = {
                "id": identity,
                "type": kind,
                "text": _text(text),
                "source_ids": source_ids or [],
                "metadata": metadata or {},
                "locators": locators or [],
                "validation_status": validation_status,
                "limitations": limitations,
                "permitted_conclusion": permitted_conclusion,
            }
        return identity

    def edge(source, target, kind, pointer, status="verified"):
        identity = "edge:" + _hash([source, target, kind, pointer])
        edges[identity] = {
            "id": identity,
            "source": source,
            "target": target,
            "type": kind,
            "provenance": {"json_locator": pointer, "verification_kind": "canonical_projection"},
            "status": status,
        }

    for index, source in enumerate(bundle.records["sources"]):
        source_id = source["id"]
        pointer = f"data/records.json#/sources/{index}"
        locators = [
            {
                "source_id": source_id,
                "json_locator": pointer,
                "url": source.get("identifiers", {}).get("exact_url"),
            }
        ]
        for value in source.get("field_resolution", {}).values():
            if isinstance(value, dict):
                locators.extend(value.get("locators", []))
        text = "\n".join(
            _text(source[k])
            for k in ("название", "авторы", "год", "метод", "задача", "датасет", "ограничения")
            if source.get(k) is not None
        )
        limits = (
            source.get("ограничения")
            or source.get("limitations")
            or source.get("validation", {}).get("notes", "")
        )
        metadata = {
            "title": source.get("название", ""),
            "record": source,
            **source.get("evidence", {}),
            "identifiers": source.get("identifiers", {}),
            "full_text_status": source.get("validation", {}).get("full_text_status"),
            "risk_flags": source.get("risk_flags", []),
            "json_locator": pointer,
        }
        node(
            source_id,
            "Source",
            text,
            [source_id],
            metadata,
            locators,
            source["validation"]["status"],
            limits,
            "Use only the reported constructs/population and the attached evidence conclusions.",
        )
        attributes = [
            ("метод", "Method", "uses_method", source.get("метод")),
            ("датасет", "Dataset", "uses_dataset", source.get("датасет")),
            (
                "population",
                "Population",
                "population",
                source.get("evidence", {}).get("population"),
            ),
            (
                "target_construct",
                "Construct",
                "measures",
                source.get("evidence", {}).get("target_construct"),
            ),
            ("species", "Population", "organism", source.get("evidence", {}).get("species")),
            ("производительность", "Result", "reports_result", source.get("производительность")),
            ("ограничения", "Limitation", "qualified_by", limits),
        ]
        for name, kind, relation, value in attributes:
            if value is None or value == "":
                continue
            identity = f"{kind.lower()}:" + _hash([source_id, name, value])
            node(
                identity,
                kind,
                value,
                [source_id],
                {key: value for key, value in metadata.items() if key != "record"},
                [{"json_locator": pointer, "field": name}],
                source["validation"]["status"],
                limits,
            )
            field_pointer = (
                pointer
                + ("/evidence/" if name in {"population", "target_construct", "species"} else "/")
                + name
            )
            edge(
                source_id,
                identity,
                relation,
                field_pointer,
                "verified"
                if source["validation"]["status"] == "verified_primary"
                else "unreviewed",
            )
    external_lookup = {}
    for source in bundle.records["sources"]:
        identifiers = source.get("identifiers", {})
        for prefix, key in (("doi:", "doi"), ("arxiv:", "arxiv_id"), ("github:", "exact_url")):
            if identifiers.get(key):
                external_lookup[prefix + identifiers[key].lower()] = source["id"]
    for source_index, source in enumerate(bundle.records["sources"]):
        for relation_index, relation in enumerate(source.get("relations", [])):
            external = relation.get("external_id")
            target = (
                relation.get("target_id")
                or external_lookup.get((external or "").lower())
                or external
            )
            if not target:
                continue
            node(target, "ExternalReference", target) if target not in nodes else None
            edge(
                source["id"],
                target,
                relation["type"],
                f"data/records.json#/sources/{source_index}/relations/{relation_index}",
            )
    aliases = bundle.aliases.get("aliases", [])
    if isinstance(aliases, dict):
        aliases = [{"alias_id": k, "canonical_id": v["canonical_id"]} for k, v in aliases.items()]
    for alias in aliases:
        old = alias.get("alias_id", alias.get("id", alias.get("alias")))
        target = alias.get("canonical_id", alias.get("canonical"))
        if old and target and target in nodes:
            node("alias:" + old, "Alias", old, [target])
            edge("alias:" + old, target, "alias_of", "data/aliases.json#/aliases/" + old)
    for cluster_index, cluster in enumerate(bundle.clusters["clusters"]):
        identity = cluster["id"]
        members = cluster.get("состав_кластера", [])
        pointer = f"data/clusters.json#/clusters/{cluster_index}"
        node(
            identity,
            "Cluster",
            str(cluster.get("тема", "")) + "\n" + str(cluster.get("синтез", "")),
            members,
            cluster,
            [{"json_locator": pointer}],
            permitted_conclusion="Thematic navigation; membership is not evidence of transfer.",
        )
        for member in members:
            if member in nodes:
                edge(member, identity, "in_cluster", pointer)
    resource_pointers = {}
    for ci, category in enumerate(bundle.resources["categories"]):
        for si, subcategory in enumerate(category["подкатегории"]):
            for ri, resource in enumerate(subcategory["ресурсы"]):
                resource_pointers[resource["resource_id"]] = (
                    f"data/ST.json#/categories/{ci}/подкатегории/{si}/ресурсы/{ri}"
                )
    for item in repository.list_resources(limit=500)["items"]:
        identity = item["resource_id"]
        node(
            identity,
            "Resource",
            _text(item),
            metadata=item,
            locators=[{"json_locator": resource_pointers[identity]}],
            validation_status=item.get("статус_валидации", "unreviewed"),
        )
    matrix = load_json(data_path(repository.data_dir, "evidence-matrix.json"))
    for index, row in enumerate(matrix["rows"]):
        identity = "evidence:" + _hash(row)
        pointer = f"data/evidence/evidence-matrix.json#/rows/{index}"
        node(
            identity,
            "EvidenceRow",
            "\n".join(
                row[k]
                for k in ("claim", "verified_evidence", "limitations", "permitted_conclusion")
            ),
            row["source_ids"],
            row,
            row["locators"],
            "curated_evidence",
            row["limitations"],
            row["permitted_conclusion"],
        )
        for source_id in row["source_ids"]:
            edge(identity, source_id, "evidenced_by", pointer)
        claim_id = "claim:" + _hash(
            [row["claim"], row["target_variable"], row["population_or_data"]]
        )
        if claim_id not in nodes:
            node(
                claim_id,
                "Claim",
                row["claim"],
                row["source_ids"],
                {"target_variable": row["target_variable"], "evidence_rows": []},
                [],
                "curated_evidence",
                [],
                [],
            )
        claim = nodes[claim_id]
        claim["source_ids"] = sorted(set(claim["source_ids"] + row["source_ids"]))
        claim["locators"].extend(row["locators"])
        claim["limitations"].append(row["limitations"])
        claim["permitted_conclusion"].append(row["permitted_conclusion"])
        claim["metadata"]["evidence_rows"].append(identity)
        edge(claim_id, identity, "has_evidence", pointer)
    novelty = load_json(data_path(repository.data_dir, "novelty-landscape.json"))
    for variant_index, variant in enumerate(novelty.get("variants", [])):
        identity = variant["id"]
        node(
            identity,
            "Variant",
            _text(variant),
            metadata=variant,
            locators=[
                {"json_locator": f"data/research/novelty-landscape.json#/variants/{variant_index}"}
            ],
            limitations=variant.get("open_condition", ""),
            permitted_conclusion=variant.get("permitted_conclusion", ""),
        )
        refs = re.findall(r"\bS\d{3,}\b", _text(variant.get("closest_analogue_refs", [])))
        nodes[identity]["source_ids"] = sorted(set(refs) & set(nodes))
        for source_id in nodes[identity]["source_ids"]:
            edge(
                identity,
                source_id,
                "closest_analogue",
                f"data/research/novelty-landscape.json#/variants/{variant_index}/closest_analogue_refs",
            )
    datasets = load_json(data_path(repository.data_dir, "human-dataset-matrix.json"))
    source_aliases = {n["text"]: n["source_ids"][0] for n in nodes.values() if n["type"] == "Alias"}
    for di, dataset in enumerate(datasets["datasets"]):
        pointer = f"data/evidence/human-dataset-matrix.json#/datasets/{di}"
        node(
            dataset["id"],
            "Dataset",
            _text(dataset),
            sorted(
                {
                    source_aliases.get(s, s)
                    for s in dataset.get("source_refs", [])
                    if source_aliases.get(s, s) in nodes
                    and nodes[source_aliases.get(s, s)]["type"] == "Source"
                }
            ),
            dataset,
            [{"json_locator": pointer}],
            limitations=dataset.get("license", ""),
        )
        for reference in dataset.get("source_refs", []):
            reference = source_aliases.get(reference, reference)
            if reference in nodes:
                edge(dataset["id"], reference, "documented_by", pointer)
    contract = load_json(data_path(repository.data_dir, "scientific-contract.json"))
    for section, kind in (
        ("entities", "Construct"),
        ("transfer_chain", "TransferConstraint"),
        ("stop_criteria", "Limitation"),
    ):
        for index, item in enumerate(contract[section]):
            pointer = f"data/research/scientific-contract.json#/{section}/{index}"
            refs = [
                r
                for r in item.get("source_refs", [])
                if r in nodes and nodes[r]["type"] == "Source"
            ]
            node(
                item["id"],
                kind,
                _text(item),
                refs,
                item,
                [{"json_locator": pointer}],
                limitations=item.get(
                    "forbidden_conclusion", item.get("prohibited_interpretation", "")
                ),
                permitted_conclusion=item.get("permitted_conclusion", item.get("decision", "")),
            )
            for ref in item.get("source_refs", []):
                if ref in nodes:
                    edge(item["id"], ref, "documented_by", pointer)
    for name, relative in DATA_PATHS.items():
        relative = str(relative).replace("\\", "/")
        if not relative.startswith(("audits/", "research/")):
            continue
        payload = load_json(data_path(repository.data_dir, name))
        identity = "audit:" + name
        node(
            identity,
            "Audit",
            name,
            metadata=payload,
            locators=[{"json_locator": "data/" + relative + "#"}],
        )
        for reference in set(re.findall(r"\b(?:S\d{3,}|ST\d{3})\b", _text(payload))):
            if reference in nodes:
                edge(identity, reference, "mentions", "data/" + relative + "#")
    for current in nodes.values():
        if len(current["source_ids"]) == 1 and current["source_ids"][0] in nodes:
            source_metadata = nodes[current["source_ids"][0]]["metadata"]
            for field in ("subject_domain", "target_construct"):
                if field in source_metadata:
                    current["metadata"].setdefault(field, source_metadata[field])
    result = {
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges.values(), key=lambda e: e["id"]),
        "counts": dict(Counter(n["type"] for n in nodes.values())),
    }
    result["fingerprint"] = _hash(result)
    return result
