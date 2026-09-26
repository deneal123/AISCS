from pathlib import Path

from scripts.refresh_github_resources import repository_url
from service.core import load_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def test_repository_url_normalizes_deep_github_links() -> None:
    assert repository_url("https://github.com/acme/demo/blob/main/file.py") == (
        "https://github.com/acme/demo"
    )
    assert repository_url("https://example.org/acme/demo") is None


def test_runtime_audit_has_reproduced_baselines_and_terminal_decisions() -> None:
    payload = load_json(DATA / "runtime-audit.json")
    candidates = {item["resource_id"]: item for item in payload["candidates"]}
    assert candidates["ST106"]["result"] == "reproduced_minimal_runtime"
    assert candidates["ST106"]["decision"] == "retain_as_embodied_simulation_baseline"
    assert candidates["ST107"]["result"] == "reproduced_browser_connectome_runtime"
    assert candidates["ST107"]["commit"] == "5880d221e21b1f3385b7246a6ffc3b2cf0029c2c"
    assert any(
        item["resource_id"] == "ST107"
        and item["commit"] == "f95f708152e22393feb2952694d4fcf7129290a6"
        for item in payload["historical_candidate_results"]
    )
    assert all(
        candidates[resource_id]["result"] == "diagnostic_terminal_decision"
        for resource_id in {"ST007", "ST008", "ST084", "ST105"}
    )
