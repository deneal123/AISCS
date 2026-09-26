"""Record the bounded FLYBOX browser runtime reproduction at a pinned commit."""
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

from service.pipeline import atomic_write_json, snapshot_repository

DATA = Path(__file__).resolve().parents[1] / "data"
DATE = "2026-09-25"
OLD = "f95f708152e22393feb2952694d4fcf7129290a6"
NEW = "5880d221e21b1f3385b7246a6ffc3b2cf0029c2c"
BASE = "https://github.com/gauravvvvvvvvvv/flybox"
ASSET = "03358c075000af5379e405b244dd31f1a0fd1401"


def read(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def find_resource(node: object) -> dict | None:
    if isinstance(node, dict):
        if node.get("resource_id") == "ST107":
            return node
        for value in node.values():
            found = find_resource(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = find_resource(value)
            if found is not None:
                return found
    return None


def main() -> None:
    records = read("records.json")
    st = read("ST.json")
    runtime = read("runtime-audit.json")
    code = read("src07-code-repository-recheck-2026-09-25.json")
    source = next(item for item in records["sources"] if item["id"] == "S737")
    resource = find_resource(st)
    assert resource is not None
    assert resource["technical_resolution"]["version_or_commit"]["value"] == OLD
    current = next(item for item in runtime["candidates"] if item["resource_id"] == "ST107")
    assert current["commit"] == OLD

    commit_url = f"{BASE}/commit/{NEW}"
    browser_doc = f"{BASE}/blob/{NEW}/docs/BROWSER_RUNTIME.md"
    worker_code = f"{BASE}/blob/{NEW}/frontend/src/simulation.worker.ts"
    loader_code = f"{BASE}/blob/{NEW}/frontend/src/connectome.ts"
    fetch_script = f"{BASE}/blob/{NEW}/scripts/fetch-browser-connectome.mjs"

    source["метод"] = "Pinned browser-only FlyBrain/MaleCNS connectome runtime with quantized weights and LIF steps; FastAPI remains an alternative backend"
    source["ограничения"] = "Experimental sensory/motor mappings and approximate 8-bit log-weight export; no float-backend parity, biological validation, natural behavior, subjective pain, ECAP fidelity or human SCS transfer."
    source["validation"]["checked_at"] = DATE
    source["validation"]["notes"] = "At pinned commit 5880d221, browser graph load and 25 LIF steps were reproduced locally; headless browser Web Worker path was also exercised in an isolated checkout."
    for path, value in (
        ("метод", source["метод"]),
        ("ограничения", source["ограничения"]),
        ("validation.checked_at", DATE),
        ("validation.notes", source["validation"]["notes"]),
    ):
        item = source["field_resolution"][path]
        item.update(state="reported", value=value, checked_at=DATE,
                    reason="Checked in pinned source and bounded local runtime audit.",
                    locators=[{"url": browser_doc, "locator": "browser runtime, graph export and limitations"},
                              {"url": worker_code, "locator": "browser Web Worker simulation path"}])

    resource["проверено"] = DATE
    resource["примечание_валидации"] = "Browser connectome runtime reproduced at the pinned commit; this is a software execution result, not biological validation."
    resource["ограничения_валидации"] = [
        "Quantized browser export and experimental mappings have no float-backend parity or biological validation.",
        "No runtime output establishes subjective pain, human spinal-cord equivalence, ECAP fidelity or SCS efficacy.",
    ]
    technical = resource["technical_resolution"]
    technical["version_or_commit"].update(
        value=NEW, reason="Current browser-runtime candidate pinned after dated HEAD and isolated checkout review.",
        checked_at=DATE, locators=[{"url": commit_url, "locator": f"commit {NEW}"}])
    technical["license"].update(
        checked_at=DATE,
        reason="LICENSE in the isolated checkout at the new pinned commit has the same SHA-256.",
        locators=[{"url": f"{BASE}/blob/{NEW}/LICENSE", "locator": "Apache-2.0; sha256=4b23242263b45bfa92cbb8d9624be82b0b266763274f0994e793a113faac0983"}])
    technical["reproducibility"].update(
        state="reported", value="browser graph load and 25 LIF steps reproduced",
        reason="Isolated pinned checkout: asset fetch, parser/step smoke, TypeScript check, Vite build and headless browser Web Worker run passed.",
        checked_at=DATE,
        locators=[{"url": browser_doc, "locator": "browser runtime instructions and limits"},
                  {"url": loader_code, "locator": "graph parser and ConnectomeBrain step"},
                  {"url": worker_code, "locator": "browser worker init and step"}])

    runtime["meta"]["checked_at"] = DATE
    runtime["meta"]["decision"] = "FlyGym minimal anatomy and FLYBOX browser connectome runtime reproduced at separate pinned commits; other candidates retain diagnostic decisions."
    runtime.setdefault("historical_candidate_results", []).append({"checked_at": "2026-09-24", **current.copy()})
    current.update(
        commit=NEW, result="reproduced_browser_connectome_runtime",
        commands=[
            "npm install --no-audit --no-fund; npm run audit:browser; npx tsc --noEmit; npx vite build",
            "node --experimental-strip-types --test smoke-connectome.test.mjs (temporary local harness, not repository code)",
            "Headless Edge/CDP Vite page and real Web Worker init/step with pinned assets",
        ],
        observations=[
            "The FlyBrain web export loaded 166700 neurons and 25088107 synapses from asset revision 03358c075000af5379e405b244dd31f1a0fd1401.",
            "An independent rerun of the local harness passed 25 LIF steps; last step had 7581 fired neurons.",
            "Headless browser worker reported mock=false, dt=0.02, step_ok=true, and no browser errors.",
            "Weights use approximate 8-bit logarithmic encoding; no parity test against the original float backend or biological validation was run.",
        ],
        decision="retain_as_reproduced_browser_runtime_with_scientific_limits",
        asset_revision=ASSET,
        locators=[{"url": browser_doc, "locator": "browser runtime and model limits"},
                  {"url": fetch_script, "locator": f"pinned FlyBrain asset revision {ASSET}"},
                  {"url": loader_code, "locator": "loadConnectome and ConnectomeBrain"},
                  {"url": worker_code, "locator": "Web Worker init and step"}],
    )
    row = next(item for item in code["rows"] if item["source_id"] == "S737")
    row["runtime_review"] = {
        "status": "reproduced_at_head",
        "commit": NEW,
        "compare_url": f"{BASE}/compare/{OLD}...{NEW}",
        "material_changes": ["frontend/src/connectome.ts", "frontend/src/simulation.worker.ts", "docs/BROWSER_RUNTIME.md"],
        "boundary": "New runtime capability is software execution evidence, not float-backend parity or biological validation.",
    }

    snapshot = snapshot_repository(DATA, label="pre-flybox-browser-runtime-refresh")
    for name, payload in (
        ("records.json", records), ("ST.json", st), ("runtime-audit.json", runtime),
        ("src07-code-repository-recheck-2026-09-25.json", code),
    ):
        atomic_write_json(DATA / name, payload)
    print(f"Updated S737/ST107 browser runtime; snapshot: {snapshot}")


if __name__ == "__main__":
    main()
