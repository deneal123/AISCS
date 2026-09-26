"""Register missing code resources linked to validated source records."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"


def _terminal(url: str, field: str) -> dict[str, Any]:
    return {
        "state": "unavailable_after_search",
        "value": None,
        "reason": "The repository is registered; immutable metadata is resolved by the GitHub refresh gate.",
        "checked_at": DATE,
        "locators": [{"url": url, "locator": f"pending GitHub {field} refresh"}],
    }


def _resource(
    resource_id: str, name: str, url: str, purpose: str, source_id: str
) -> dict[str, Any]:
    return {
        "название": name,
        "ссылка": url,
        "назначение": purpose,
        "задачи": ["Задача 1", "Задача 2"],
        "статус_валидации": "verified_primary",
        "проверено": DATE,
        "примечание_валидации": (
            f"Primary repository linked to {source_id}; code availability does not prove "
            "biological validity, ECAP equivalence, or SCS transfer."
        ),
        "resource_id": resource_id,
        "проверенные_утверждения": [
            f"The public primary repository exists and is linked to canonical source {source_id}."
        ],
        "ограничения_валидации": [
            "Runtime reproduction is a separate gate.",
            "No repository output may be interpreted as subjective pain or human spinal-cord equivalence.",
        ],
        "technical_resolution": {
            "version_or_commit": _terminal(url, "commit"),
            "license": _terminal(url, "license"),
            "data_access": {
                "state": "reported",
                "value": "public repository",
                "reason": "The repository landing page is publicly reachable.",
                "checked_at": DATE,
                "locators": [{"url": url, "locator": "repository landing page"}],
            },
            "reproducibility": _terminal(url, "runtime"),
        },
    }


def build() -> dict[str, Any]:
    payload = load_json(DATA / "ST.json")
    existing = {
        resource["resource_id"]
        for category in payload["categories"]
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
    }
    additions = [
        _resource(
            "ST105",
            "fly-brain-snntorch",
            "https://github.com/Neuromorphicism/fly-brain-snntorch",
            "snnTorch implementation candidate for Drosophila connectome simulation.",
            "S733",
        ),
        _resource(
            "ST106",
            "FlyGym source repository",
            "https://github.com/NeLy-EPFL/flygym",
            "Official embodied Drosophila simulation codebase used by NeuroMechFly v2.",
            "S734",
        ),
        _resource(
            "ST107",
            "FLYBOX",
            "https://github.com/gauravvvvvvvvvv/flybox",
            "Open-source sandbox candidate for Drosophila nervous-system experiments.",
            "S737",
        ),
        _resource(
            "ST108",
            "connconstr",
            "https://github.com/emebeiran/connconstr",
            "Code and generated data for connectome-constrained RNN identifiability experiments.",
            "S743",
        ),
        _resource(
            "ST109",
            "wormvae",
            "https://github.com/TuragaLab/wormvae",
            "Reference implementation of connectome sparsity/count ablations for CC-LVM.",
            "S745",
        ),
    ]
    duplicate = existing & {resource["resource_id"] for resource in additions}
    if duplicate:
        raise ValueError(f"resource IDs already exist: {sorted(duplicate)}")
    target = next(
        subcategory
        for category in payload["categories"]
        if category["id"] == "C1"
        for subcategory in category["подкатегории"]
        if subcategory["id"] == "C1.2"
    )
    target["ресурсы"].extend(additions)
    items = [
        resource
        for category in payload["categories"]
        for subcategory in category.get("подкатегории", [])
        for resource in subcategory.get("ресурсы", [])
    ]
    statuses = Counter(resource["статус_валидации"] for resource in items)
    payload["meta"].update(
        {
            "всего_ресурсов": len(items),
            "дата_валидации": DATE,
            "проверено_по_первичному_источнику": statuses["verified_primary"],
            "статусы_ресурсов": dict(sorted(statuses.items())),
            "незавершенных_ресурсов": statuses["unverified"] + statuses["pending"],
        }
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = build()
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-code-resource-addition")
        atomic_write_json(DATA / "ST.json", payload)
        report = validate_repository(DATA)
        if not report["ok"]:
            raise RuntimeError(f"restore {snapshot}: {'; '.join(report['errors'])}")
    print(
        json.dumps(
            {"ok": True, "applied": args.apply, "resources": payload["meta"]["всего_ресурсов"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
