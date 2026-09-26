"""Record a bounded primary RSL catalogue pass for NS-15."""

# ruff: noqa: E501 -- preserve exact catalogue titles and search boundaries.

import argparse
import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-25"

RECORDS = [
    {
        "catalogue_id": "01004299840",
        "author": "Исагулян Эмиль Давидович",
        "title": "Хроническая электростимуляция спинного и головного мозга в лечении нейрогенных болевых синдромов",
        "year": 2006,
        "scope": "Clinical spinal/brain stimulation for neurogenic pain; catalogue title only",
    },
    {
        "catalogue_id": "01003027412",
        "author": "Богачева Ирина Николаевна",
        "title": "Нейрональные механизмы формирования локомоторного паттерна при электрической стимуляции спинного мозга",
        "year": 2006,
        "scope": "Spinal stimulation and locomotor-pattern mechanisms; catalogue title only",
    },
    {
        "catalogue_id": "01010888313",
        "author": "Курмуков Анвар Илдарович",
        "title": "Иерархическая структура коннектомов головного мозга",
        "year": 2021,
        "scope": "Brain connectome structure; species, model and comparator not inferred from catalogue title",
    },
    {
        "catalogue_id": "01009687642",
        "author": "Якимова Анна Олеговна",
        "title": "Нарушения формирования нервных центров и поведения у мутантов по гену sbr (Dm nxf1) Drosophila melanogaster",
        "year": 2018,
        "scope": "Drosophila neural development and behavior; no connectome simulation established by catalogue title",
    },
]


def updated() -> tuple[dict, dict]:
    protocol = json.loads((DATA / "search-protocol.json").read_text(encoding="utf-8"))
    stream = next(item for item in protocol["search_streams"] if item["id"] == "NS-15")
    if stream["source_ids"] or stream["status"] != "open" or any(item["id"] == "NS-RUN-2026-09-25-08" for item in protocol["search_runs"]):
        raise ValueError("NS-15 initial pass already recorded")
    stream["status"] = "initial_pass_recorded"
    stream["coverage_note"] = "Four primary RSL catalogue records were verified as bibliographic leads. Their full methods were not accessed. eLIBRARY defaultx.asp redirects to ip_blocked.asp from this environment. RSL broader queries, eLIBRARY via an authorized route, official university repositories, backward/forward citations and a later update remain open."
    queries = [
        '"спинномозговая стимуляция"',
        "электростимуляция спинного мозга",
        '"коннектом"',
        "ноцицепция Drosophila",
        '"Drosophila" коннектом',
    ]
    protocol["search_runs"].append({
        "id": "NS-RUN-2026-09-25-08",
        "date": DATE,
        "queries": queries,
        "primary_urls": [f"https://search.rsl.ru/ru/record/{item['catalogue_id']}" for item in RECORDS],
        "new_mechanism_classes": [],
        "direct_drosophila_ecap_scs_analogue_found": False,
        "saturation": False,
    })
    audit = {
        "meta": {
            "schema_version": "1.0.0",
            "checked_at": DATE,
            "status": "in_progress",
            "scope": "NS-15 Russian-language dissertations and primary catalogue records",
            "decision": "four_adjacent_bibliographic_leads_no_full_method_checked",
        },
        "queries": queries,
        "rsl_catalogue_leads": [
            {
                **item,
                "url": f"https://search.rsl.ru/ru/record/{item['catalogue_id']}",
                "access_level": "primary_catalogue_record_only",
                "locator": "RSL record HTML title and MARC bibliographic fields",
                "full_method_status": "not_checked",
                "direct_analogue_status": "not_established_from_catalogue",
            }
            for item in RECORDS
        ],
        "access_boundaries": [
            {
                "site": "eLIBRARY.RU",
                "status": "blocked_from_current_environment",
                "checked_at": DATE,
                "url": "https://www.elibrary.ru/defaultx.asp",
                "locator": "GET redirects with HTTP 302 Location: /ip_blocked.asp; this does not establish database coverage",
            }
        ],
        "remaining": [
            "Full primary methods for relevant dissertations",
            "Authorized eLIBRARY search and independent official university repositories",
            "Exact/synonym/author searches, backward/forward snowballing and later dated update",
        ],
    }
    return protocol, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    protocol, audit = updated()
    if not args.apply:
        print("Dry run: four RSL bibliographic leads; NS-15 remains open")
        return
    snapshot = snapshot_repository(DATA, label="pre-ns15-rsl-catalogue-pass")
    atomic_write_json(DATA / "search-protocol.json", protocol)
    atomic_write_json(DATA / "ns15-russian-prior-art-audit.json", audit)
    print(f"Recorded NS-15 RSL pass; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
