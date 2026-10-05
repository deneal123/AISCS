"""Discover registered upstream candidates without changing scientific records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "research/.work/simulator-evaluation"
REGISTRY = Path(__file__).with_name("registry.json")


def load(path):
    return json.loads(path.read_text("utf-8"))


def save(path, obj):
    path = path.resolve()
    if not (
        path.is_relative_to(WORK.resolve())
        or path.is_relative_to((ROOT / "simulation").resolve())
    ):
        raise ValueError("Output outside simulation or its designated .work directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = WORK / "io" / (uuid.uuid4().hex + ".json")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def resources(value):
    if isinstance(value, dict):
        if "resource_id" in value:
            yield value
        else:
            for child in value.values():
                yield from resources(child)
    elif isinstance(value, list):
        for child in value:
            yield from resources(child)


def repository_urls(text):
    return sorted(
        {
            f"{owner}/{name.rstrip('.').removesuffix('.git')}"
            for owner, name in re.findall(
                r"https://github\.com/([\w.-]+)/([\w.-]+)", text
            )
        }
    )


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    if not (WORK / "baseline.json").exists():
        protected = [p for p in (ROOT / "research/data").rglob("*") if p.is_file()]
        protected += [
            p
            for p in (ROOT / "publications/documents/PUB-001").rglob("*")
            if p.is_file()
        ]
        protected += [
            ROOT / "research/TODO.md",
            ROOT / "docs/material/IPR_chistovoi-tekst_2026-2030.md",
        ]
        save(
            WORK / "baseline.json",
            {
                "protected": {
                    p.relative_to(ROOT).as_posix(): hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()
                    for p in protected
                },
                "gitmodules": (ROOT / ".gitmodules").read_text("utf-8"),
                "git_status": subprocess.check_output(
                    ["git", "status", "--short"], cwd=ROOT, text=True
                ),
            },
        )
    st = load(ROOT / "research/data/ST.json")
    found = {}

    def add(slug, origin, sid=None, pin=None, license_name=None):
        # One upstream has moved organizations; it is a single comparison.
        if slug == "NSSIL/ScaleBreak-FlyVis":
            slug = "nalin-dhiman/ScaleBreak-FlyVis"
        if slug == "smpuglie/Pugliese_cpg_2025":
            slug = "smpuglie/Pugliese_2026"
        row = found.setdefault(
            slug,
            {
                "repository": slug,
                "url": "https://github.com/" + slug + ".git",
                "origins": [],
                "source_ids": [],
                "recorded_commit": None,
                "recorded_license": None,
                "status": "discovered",
            },
        )
        if origin not in row["origins"]:
            row["origins"].append(origin)
        if sid and sid not in row["source_ids"]:
            row["source_ids"].append(sid)
        if pin:
            row["recorded_commit"] = pin
        if license_name:
            row["recorded_license"] = license_name

    selected = list(resources(st["categories"][0]))
    selected += [r for r in resources(st) if r["resource_id"] == "ST084"]
    for row in selected:
        url = row.get("ссылка") or ""
        slugs = repository_urls(url)
        if not slugs:
            continue
        tech = row.get("technical_resolution", {})
        add(
            slugs[0],
            row["resource_id"],
            pin=tech.get("version_or_commit", {}).get("value"),
            license_name=tech.get("license", {}).get("value"),
        )
    for source in load(ROOT / "research/data/records.json")["sources"]:
        body = json.dumps(source, ensure_ascii=False)
        if re.search(
            r"drosophila|flywire|connectome-constrained|ECAP|spinal cord stimulation",
            body,
            re.IGNORECASE,
        ):
            for slug in repository_urls(body):
                add(slug, "canonical-source", source["id"])
    audit = ROOT / "research/data/audits/drosophila/drosophila-connectome-audit.json"
    body = audit.read_text("utf-8")
    for slug in repository_urls(body):
        # Versioned author implementation or connectome-preparation support, not generic dependencies.
        add(slug, "drosophila-connectome-audit")
        matches = re.findall(
            r"https://github\.com/"
            + re.escape(slug)
            + r"/(?:blob|tree)/([a-f0-9]{40})",
            body,
        )
        if matches and not found[slug]["recorded_commit"]:
            found[slug]["recorded_commit"] = matches[0]
    add("NeLy-EPFL/flygym-gymnasium", "official-FlyGym-1.x-compatibility")
    for n, row in enumerate(
        sorted(found.values(), key=lambda x: x["repository"].lower()), 1
    ):
        row["id"] = f"SIM-{n:03d}"
        row["path"] = "simulation/sidecars/" + row["repository"].replace("/", "--")
    rows = sorted(found.values(), key=lambda x: x["id"])
    if REGISTRY.exists():
        old = {r["repository"]: r for r in load(REGISTRY)["candidates"]}
        for row in rows:
            previous = old.get(row["repository"])
            if previous:
                previous["origins"] = sorted(set(previous["origins"] + row["origins"]))
                previous["source_ids"] = sorted(
                    set(previous["source_ids"] + row["source_ids"])
                )
        rows = [old.get(r["repository"], r) for r in rows]
    save(
        REGISTRY,
        {
            "schema_version": "1.0",
            "discovered_at": "2026-10-04",
            "scientific_gate": "G0_REVISE",
            "knowledge_generation": "g-56b4c46e48ad7a8b5db92c99",
            "repository_aliases": {
                "NSSIL/ScaleBreak-FlyVis": "nalin-dhiman/ScaleBreak-FlyVis",
                "smpuglie/Pugliese_cpg_2025": "smpuglie/Pugliese_2026",
            },
            "policy": {
                "cpu_threads": 4,
                "memory_bytes": 4 * 1024**3,
                "vram_bytes": 5 * 1024**3,
                "host_reserve_bytes": 2 * 1024**3,
                "install_seconds": 1800,
                "smoke_seconds": 600,
                "functional_seconds": 1800,
                "seeds": [1, 2, 3],
                "lfs_attempts": 2,
                "disk_reserve_bytes": 20 * 1024**3,
            },
            "candidates": rows,
        },
    )
    print(f"{len(rows)} unique repositories; baseline preserved")


if __name__ == "__main__":
    main()
