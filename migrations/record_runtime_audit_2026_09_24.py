"""Record simulator runtime checks and resolve repository-license fallbacks."""

# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from service.core import load_json
from service.integrity import validate_repository
from service.pipeline import atomic_write_json, snapshot_repository
from service.st_curation import iter_resources

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DATE = "2026-09-24"

LICENSES = {
    "ST105": ("MIT", "22c94f0b68bea259f75866399bdfa127f2c3e86260b664c281029a509d948b97"),
    "ST106": ("Apache-2.0", "4e89fc37e50d41ea81616b413b23db4e8db395898930490fced1fa7d1eae863c"),
    "ST107": ("Apache-2.0", "4b23242263b45bfa92cbb8d9624be82b0b266763274f0994e793a113faac0983"),
}


def resolution(state: str, value: str | None, reason: str, url: str, locator: str) -> dict[str, Any]:
    return {
        "state": state,
        "value": value,
        "reason": reason,
        "checked_at": DATE,
        "locators": [{"url": url, "locator": locator}],
    }


def runtime_payload() -> dict[str, Any]:
    return {
        "meta": {
            "schema_version": "1.0.0",
            "checked_at": DATE,
            "host": "Windows; isolated temporary checkouts; pinned repository commits",
            "decision": "FlyGym is the only reproduced minimal embodied baseline in this pass",
        },
        "candidates": [
            {
                "resource_id": "ST106",
                "commit": "38c8ec61034cd59bc5ba0de20688d4a3c0000d60",
                "result": "reproduced_minimal_runtime",
                "commands": [
                    "uv run --frozen python -c 'import flygym; print(flygym.__file__)'",
                    "uv run --frozen --extra dev pytest tests/core/test_anatomy.py -q -o addopts=''",
                ],
                "observations": [
                    "Package import succeeded in an isolated environment.",
                    "133 anatomy tests passed at the pinned commit.",
                    "This validates installation and core anatomy only, not a nociception model.",
                ],
                "decision": "retain_as_embodied_simulation_baseline",
            },
            {
                "resource_id": "ST007",
                "commit": "a3db62f9436074e485c0278290c2164ed6150808",
                "result": "diagnostic_terminal_decision",
                "commands": [
                    "python -m compileall -q .",
                    "python main.py --help",
                    "python main.py --t_run 0.1 --n_run 1 --pytorch --disable-spike-io --no_log_file",
                ],
                "observations": [
                    "Source compilation and CLI discovery succeeded.",
                    "Benchmark startup stopped at missing pandas outside the declared Conda stack.",
                    "The declared environment combines Python 3.10, CUDA/backend-specific packages and unpinned torch.",
                ],
                "decision": "retain_as_connectome_backend_candidate_not_reproduced",
            },
            {
                "resource_id": "ST008",
                "commit": "3a035275148e97539711728422548bffe2a77566",
                "result": "diagnostic_terminal_decision",
                "commands": ["git checkout pinned commit"],
                "observations": [
                    "Checkout failed to materialize data/plastic_weights.pt.",
                    "The Git LFS server returned 404 for the referenced object.",
                ],
                "decision": "exclude_until_pinned_lfs_object_is_restored",
            },
            {
                "resource_id": "ST105",
                "commit": "fe55fb0cff275a2b6b54926524c8d831838e32fc",
                "result": "diagnostic_terminal_decision",
                "commands": ["python -m compileall -q .", "python fly_brain.py --help"],
                "observations": [
                    "Source compilation succeeded; execution requires an unpinned requirements set.",
                    "The entrypoint imports plotting dependencies before CLI handling.",
                    "The repository warns that its dense tensor can require about 60 GB; it was not generated.",
                ],
                "decision": "exclude_from_bounded_prototype_until_sparse_locked_runner_exists",
            },
            {
                "resource_id": "ST084",
                "commit": "71ecf53d78eaffaf1a57ed7b0ccf5d458abc9f33",
                "result": "diagnostic_terminal_decision",
                "commands": ["python -m compileall -q ."],
                "observations": [
                    "Source compilation succeeded.",
                    "The repository reports failed visual, conditioning and survival validation gates.",
                ],
                "decision": "exclude_as_scientific_simulation_baseline",
            },
            {
                "resource_id": "ST107",
                "commit": "f95f708152e22393feb2952694d4fcf7129290a6",
                "result": "diagnostic_terminal_decision",
                "commands": ["python -m compileall -q ."],
                "observations": [
                    "Python sources compiled, but the repository is an application platform rather than a neural simulator.",
                ],
                "decision": "exclude_as_simulator_candidate",
            },
        ],
        "boundary": (
            "Runtime reproduction does not establish biological validity, subjective pain, "
            "human spinal-cord equivalence, ECAP fidelity, or SCS efficacy."
        ),
    }


def build_outputs(data_dir: Path = DATA) -> dict[str, dict[str, Any]]:
    st = load_json(data_dir / "ST.json")
    resources = {resource["resource_id"]: resource for _, _, resource in iter_resources(st)}
    for resource_id, (spdx, digest) in LICENSES.items():
        resource = resources[resource_id]
        url = resource["ссылка"]
        resource["technical_resolution"]["license"] = resolution(
            "reported",
            spdx,
            "License text was checked at the pinned commit after API metadata was inconclusive.",
            f"{url}/blob/{resource['technical_resolution']['version_or_commit']['value']}/LICENSE",
            f"LICENSE; sha256={digest}",
        )
        exclusion = "Excluded from the reproducible dissertation stack until an explicit license is confirmed by the owner or a tagged release."
        resource["ограничения_валидации"] = [
            item for item in resource["ограничения_валидации"] if item != exclusion
        ]

    flygym = resources["ST106"]
    flygym["technical_resolution"]["reproducibility"] = resolution(
        "reported",
        "import succeeded; 133 core anatomy tests passed",
        "An isolated uv environment reproduced package import and the bounded core anatomy suite.",
        "https://github.com/NeLy-EPFL/flygym/commit/38c8ec61034cd59bc5ba0de20688d4a3c0000d60",
        "runtime-audit ST106 commands and results",
    )
    for resource_id, reason in {
        "ST007": "CLI loaded, but the bounded PyTorch benchmark requires the repository's dedicated Conda dependency stack.",
        "ST008": "Pinned checkout cannot retrieve a required Git LFS weight object; the server returned 404.",
        "ST105": "A bounded sparse runner and locked environment are absent; the documented dense path can require about 60 GB.",
        "ST084": "Repository-reported scientific validation gates failed; source compilation is not model validation.",
        "ST107": "The resource is an application platform, not a neural simulator candidate.",
    }.items():
        resource = resources[resource_id]
        resource["technical_resolution"]["reproducibility"] = resolution(
            "unavailable_after_search",
            None,
            reason,
            resource["ссылка"],
            "runtime-audit terminal decision",
        )

    reported_licenses = sum(
        resource["technical_resolution"]["license"]["state"] == "reported"
        for resource in resources.values()
    )
    st["meta"].update({"проверено": DATE, "reported_software_licenses": reported_licenses})

    audit = load_json(data_dir / "audit-report.json")
    audit["meta"]["generated_at"] = DATE
    audit["runtime_audit"] = {
        "checked_at": DATE,
        "candidate_resource_ids": [item["resource_id"] for item in runtime_payload()["candidates"]],
        "reproduced_resource_ids": ["ST106"],
        "terminal_decision_resource_ids": ["ST007", "ST008", "ST084", "ST105", "ST107"],
    }
    audit["current_corpus"]["reported_spdx_licenses"] = reported_licenses

    validation_log = load_json(data_dir / "validation-log.json")
    validation_log.setdefault("searches", []).append(
        {
            "search_id": "RUNTIME-2026-09-24-01",
            "date": DATE,
            "stream": "simulator runtime reproduction",
            "query": "pinned local checkout and bounded executable checks",
            "urls_reviewed": [resources[item]["ссылка"] for item in ["ST007", "ST008", "ST084", "ST105", "ST106", "ST107"]],
            "resource_ids": ["ST007", "ST008", "ST084", "ST105", "ST106", "ST107"],
            "decision": "FlyGym retained; other candidates have recorded terminal decisions",
        }
    )
    validation_log["meta"]["checked_at"] = DATE
    return {
        "ST.json": st,
        "audit-report.json": audit,
        "validation-log.json": validation_log,
        "runtime-audit.json": runtime_payload(),
    }


def validate_outputs(outputs: dict[str, dict[str, Any]], data_dir: Path = DATA) -> None:
    with tempfile.TemporaryDirectory(prefix="research-runtime-") as temporary:
        target = Path(temporary)
        for path in data_dir.glob("*.json"):
            shutil.copy2(path, target / path.name)
        for name, payload in outputs.items():
            atomic_write_json(target / name, payload)
        report = validate_repository(target)
        if not report["ok"]:
            raise ValueError("; ".join(report["errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    outputs = build_outputs()
    validate_outputs(outputs)
    snapshot = None
    if args.apply:
        snapshot = snapshot_repository(DATA, label="pre-runtime-audit")
        for name, payload in outputs.items():
            atomic_write_json(DATA / name, payload)
    print(json.dumps({"ok": True, "applied": args.apply, "snapshot": str(snapshot) if snapshot else None}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
