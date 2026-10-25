"""One path registry for simulation tools; upstream and historical receipts stay put."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIMULATION = ROOT / "simulations"
DATA = SIMULATION / "data"
DOCS = SIMULATION / "docs"
SCRIPTS = SIMULATION / "scripts"
ARTIFACTS = SIMULATION / "artifacts"
WORK = ROOT / "research/.work/simulator-evaluation"
REGISTRY = DATA / "registry.json"
PROFILES = DATA / "profiles.json"
ASSESSMENT = DATA / "assessment.json"
REPORT = SIMULATION / "REPORT.md"
TODO = SIMULATION / "TODO.md"
