"""Read-only structural, evidence, provenance, link and submodule checks."""

import json
import re
import subprocess
from urllib.parse import unquote

from checks import LABELS, checklist
from paths import ARTIFACTS, REGISTRY, ROOT, SIMULATION
from publish_artifacts import publish
from report_views import render

ROOT_FILES = {"README.md", "TODO.md", "REPORT.md"}
ROOT_DIRS = {
    "data",
    "docs",
    "scripts",
    "environments",
    "tests",
    "artifacts",
    "sidecars",
}


def git(*args):
    return subprocess.run(
        ["git", "-c", "core.safecrlf=false", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.strip()


def markdown_links(path):
    errors = []
    for raw in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        raw = raw.removeprefix("<").removesuffix(">")
        if raw.startswith(("https://", "http://", "mailto:")):
            continue
        name, _, anchor = unquote(raw).partition("#")
        target = path.parent / name if name else path
        if not target.exists():
            errors.append(f"Broken link: {path.relative_to(ROOT)} -> {raw}")
        elif anchor and target.suffix == ".md":
            text = target.read_text(encoding="utf-8")
            ids = set(re.findall(r'<a id="([^"]+)"', text))
            for title in re.findall(r"^#+ (.+)$", text, flags=re.MULTILINE):
                ids.add(re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-"))
            if anchor not in ids:
                errors.append(f"Broken anchor: {path.relative_to(ROOT)} -> {raw}")
    return errors


def followup_errors(row):
    review = row.get("followup_review")
    if not review:
        return []
    errors = []
    states = {item["id"]: item["status"] for item in checklist(row)}
    items = review.get("checks", [])
    if (
        not review.get("date")
        or not items
        or len({item["id"] for item in items}) != len(items)
    ):
        errors.append("Incomplete or duplicate followup: " + row["id"])
    for item in items:
        if item["id"] not in LABELS or item.get("decision") not in {
            "resolved",
            "confirmed_blocker",
        }:
            errors.append("Invalid followup decision: " + row["id"])
        if not item.get("finding") or not item.get("evidence"):
            errors.append("Missing followup finding/evidence: " + row["id"])
        for relative in item.get("evidence", []):
            if not (ROOT / relative).is_file():
                errors.append("Missing followup receipt: " + relative)
        if item.get("decision") == "resolved" and states.get(item["id"]) != "passed":
            errors.append(
                "Followup falsely closes check: " + row["id"] + "/" + item["id"]
            )
        if (
            item.get("decision") == "confirmed_blocker"
            and states.get(item["id"]) == "passed"
        ):
            errors.append(
                "Followup contradicts passing check: " + row["id"] + "/" + item["id"]
            )
    return errors


def validate(registry, submodules=True):
    errors = []
    for path in SIMULATION.iterdir():
        # Python caches are ignored implementation state, never source material.
        if path.name == "__pycache__":
            continue
        if (
            path.is_file()
            and path.name not in ROOT_FILES
            or path.is_dir()
            and path.name not in ROOT_DIRS
        ):
            errors.append("Unexpected simulation root entry: " + path.name)
    rows = registry["candidates"]
    for directory, allowed in {
        "data": {"registry.json", "profiles.json", "assessment.json"},
        "docs": {
            "WORKFLOW.md",
            "generator-requirements.md",
            "nociception-and-recording.md",
        },
    }.items():
        actual = {p.name for p in (SIMULATION / directory).iterdir()}
        if actual != allowed:
            errors.append(
                f"Unexpected file set in {directory}: {sorted(actual ^ allowed)}"
            )
    expected = {f"SIM-{i:03d}" for i in range(1, 34)} - {"SIM-028"}
    if {c["id"] for c in rows} != expected or len(rows) != 32:
        errors.append("Expected exactly the 32 registered SIM IDs")
    for field in ("id", "path", "repository"):
        if len({c[field] for c in rows}) != len(rows):
            errors.append("Duplicate candidate " + field)
    profiles = json.loads(
        (SIMULATION / "data/profiles.json").read_text(encoding="utf-8")
    )
    if not set(profiles).issubset(expected):
        errors.append("Unknown profile IDs")
    for row in rows:
        sid = row["id"]
        errors.extend(followup_errors(row))
        if not re.fullmatch(r"[a-f0-9]{40}", row["commit"]):
            errors.append("Invalid pin: " + sid)
        for item in checklist(row):
            if item["status"] == "passed" and not item["evidence"]:
                errors.append(f"Missing evidence: {sid}/{item['id']}")
            for evidence in item["evidence"]:
                if (
                    not evidence.startswith(("https://", "http://"))
                    and not (ROOT / evidence).is_file()
                ):
                    errors.append(f"Missing receipt: {sid}: {evidence}")
        review = row.get("launch_review")
        if review:
            for key in (
                "status",
                "date",
                "summary",
                "scope",
                "receipts",
                "memory",
                "resolved_issues",
                "strengths",
                "weaknesses",
                "options",
                "recommendation",
            ):
                if key not in review:
                    errors.append(f"Incomplete review: {sid}/{key}")
        for visual in row.get("visual_artifacts", []):
            if not all(
                visual.get(key)
                for key in ("file", "source", "sha256", "caption", "scope")
            ):
                errors.append("Incomplete visual provenance: " + sid)
        if submodules:
            if git("-C", str(ROOT / row["path"]), "rev-parse", "HEAD") != row["commit"]:
                errors.append("Submodule pin mismatch: " + sid)
            if git("-C", str(ROOT / row["path"]), "status", "--porcelain"):
                errors.append("Dirty source checkout: " + sid)
            index = git("ls-files", "--stage", "--", row["path"])
            if not index.startswith("160000 " + row["commit"] + " 0\t"):
                errors.append("Gitlink mismatch: " + sid)
            prefix = "submodule.simulation/" + sid
            if (
                git("config", "-f", ".gitmodules", "--get", prefix + ".path")
                != row["path"]
            ):
                errors.append("Submodule registration mismatch: " + sid)
            if (
                git("config", "-f", ".gitmodules", "--get", prefix + ".url")
                != row["url"]
            ):
                errors.append("Submodule URL mismatch: " + sid)
    try:
        publish(registry, check=True)
    except ValueError as exc:
        errors.append(str(exc))
    for path, content in render(registry).items():
        if not path.is_file() or path.read_bytes() != content.encode("utf-8"):
            errors.append("Stale generated file: " + path.relative_to(ROOT).as_posix())
    gallery_dirs = {p.name for p in ARTIFACTS.iterdir() if p.is_dir()}
    if gallery_dirs != expected:
        errors.append("Artifact directory set differs from SIM IDs")
    for row in rows:
        allowed = {"README.md", "manifest.json"} | {
            v["file"] for v in row.get("visual_artifacts", [])
        }
        for path in (ARTIFACTS / row["id"]).iterdir():
            if path.name not in allowed:
                errors.append(
                    "Unregistered artifact: " + path.relative_to(ROOT).as_posix()
                )
    for folder in (
        SIMULATION,
        SIMULATION / "docs",
        SIMULATION / "data",
        SIMULATION / "scripts",
        SIMULATION / "tests",
        ARTIFACTS,
    ):
        paths = folder.glob("*") if folder == SIMULATION else folder.rglob("*")
        for path in paths:
            if not path.is_file() or path.suffix not in {
                ".md",
                ".py",
                ".json",
                ".mjs",
                ".cjs",
                ".jl",
                ".R",
            }:
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                errors.append("Not UTF-8: " + str(path))
                continue
            if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
                errors.append(
                    "Expected UTF-8/LF without BOM: "
                    + path.relative_to(ROOT).as_posix()
                )
            if path.suffix == ".md":
                errors.extend(markdown_links(path))
            if path.suffix == ".md" and (
                "simulation/evaluation-report.md" in text
                or "simulation/registry.json" in text
            ):
                errors.append("Stale active path: " + path.relative_to(ROOT).as_posix())
    return errors


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    errors = validate(registry)
    print(
        json.dumps(
            {"candidates": len(registry["candidates"]), "errors": errors},
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
