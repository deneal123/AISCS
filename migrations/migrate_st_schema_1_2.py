"""Assign stable IDs and normalized validation fields to every ST resource."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from service.core import load_json
from service.pipeline import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "ST.json"


def iter_resources(payload: dict):
    for category in payload.get("categories", []):
        for subcategory in category.get("подкатегории", []):
            yield from subcategory.get("ресурсы", [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-way migration to ST schema 1.2; writes require --apply."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate the plan without writing")
    mode.add_argument("--apply", action="store_true", help="write the migration output")
    return parser.parse_args()


def main(*, apply: bool) -> None:
    payload = load_json(PATH)
    resources = list(iter_resources(payload))
    for index, resource in enumerate(resources, start=1):
        resource["resource_id"] = f"ST{index:03d}"
        resource.setdefault("проверенные_утверждения", [])
        resource.setdefault("ограничения_валидации", [])
    counts = Counter(resource["статус_валидации"] for resource in resources)
    payload["meta"].update(
        {
            "версия": "1.2.0",
            "resource_schema_version": "1.2.0",
            "resource_id_policy": "stable STNNN in document order",
            "дата_валидации": date.today().isoformat(),
            "статусы_ресурсов": dict(sorted(counts.items())),
        }
    )
    if apply:
        atomic_write_json(PATH, payload)
    print(
        {
            "resources": len(resources),
            "statuses": dict(sorted(counts.items())),
            "writes": apply,
        }
    )


if __name__ == "__main__":
    arguments = parse_args()
    main(apply=arguments.apply)
