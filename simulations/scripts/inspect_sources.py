"""Read-only upstream inventory; source checks are not simulation validation."""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections import Counter

sys.dont_write_bytecode = True
from inventory import REGISTRY, ROOT, WORK, load, save

ROLES = {
    "artem-x-meta/fly-arena": "embodied",
    "chaobrain/fitting_drosophila_whole_brain_spiking_model": "neural-fitting",
    "cnqso/infinite-sugar": "neural",
    "cooneypc4/larval_escape_manuscript": "author-analysis",
    "emebeiran/connconstr": "method-comparator",
    "eonsystemspbc/fly-brain": "neural",
    "erankopel/maleCNS-depth": "connectome-preparation",
    "flyconnectome/2025malecns": "connectome-preparation",
    "gauravvvvvvvvvv/flybox": "browser-neural",
    "hsseung/OpticLobe.jl": "connectome-preparation",
    "htem/BANC-project": "connectome-preparation",
    "htem/FANC_auto_recon": "connectome-preparation",
    "jajmcallister/Conn_ESN_Paper": "method-comparator",
    "JNLiew/flylif_orientation_maps": "neural",
    "legacyindiesubmissions-ai/claude-fly": "embodied",
    "MakazhanAlpamys/soup-connectome": "neural",
    "murthylab/flywire-network-analysis": "connectome-preparation",
    "nalin-dhiman/Connectome-Constrained-Neural-Networks": "neural",
    "nalin-dhiman/ScaleBreak-FlyVis": "method-comparator",
    "NeLy-EPFL/flygym": "body-environment",
    "NeLy-EPFL/flygym-gymnasium": "body-environment-compatibility",
    "Neuromorphicism/fly-brain-snntorch": "neural",
    "nftechie/doomfly": "embodied-game",
    "philshiu/Drosophila_brain_model": "neural",
    "rdarie/modular-bionic-interface-2026": "human-neural-interface-comparator",
    "seung-lab/FlyConnectome": "connectome-preparation",
    "smpuglie/Pugliese_2026": "motor-cpg",
    "smpuglie/Pugliese_cpg_2025": "motor-cpg",
    "snedea/flybrain": "browser-neural",
    "Stavros963/fcta": "connectome-analysis",
    "TuragaLab/flyvis": "visual-neural",
    "TuragaLab/wormvae": "other-organism-comparator",
    "YijieYin/connectome_data_prep": "connectome-preparation",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(row):
    base = ROOT / row["path"]
    paths = sorted(p for p in base.rglob("*") if p.is_file() and ".git" not in p.parts)
    result = {
        "repository": row["repository"],
        "commit": row["commit"],
        "files": {p.relative_to(base).as_posix(): digest(p) for p in paths},
        "dependency_files": {},
        "licenses": {},
        "readmes": {},
        "test_files": [],
        "static_python": {"parsed": 0, "errors": []},
    }
    for path in paths:
        rel = path.relative_to(base).as_posix()
        lower = path.name.lower()
        if lower.startswith(("license", "copying")):
            result["licenses"][rel] = {
                "sha256": digest(path),
                "text": path.read_text("utf-8", errors="replace"),
            }
        if (
            (lower.startswith("requirements") and path.suffix in {".txt", ".in"})
            or (lower.startswith("environment") and path.suffix in {".yml", ".yaml"})
        ) or lower in {
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "package.json",
            "project.toml",
            "cargo.toml",
            "cmakelists.txt",
            "makefile",
        }:
            result["dependency_files"][rel] = path.read_text("utf-8", errors="replace")[
                :50000
            ]
        if lower.startswith("readme") and path.stat().st_size < 300000:
            result["readmes"][rel] = path.read_text("utf-8", errors="replace")
        if "test" in lower and path.suffix in {".py", ".js", ".ts", ".cpp", ".sh"}:
            result["test_files"].append(rel)
        if path.suffix == ".py" and path.stat().st_size < 1000000:
            try:
                ast.parse(path.read_text("utf-8-sig", errors="strict"), filename=rel)
                result["static_python"]["parsed"] += 1
            except (SyntaxError, UnicodeError) as exc:
                result["static_python"]["errors"].append(
                    {"path": rel, "error": str(exc)}
                )
    text = "\n".join(result["readmes"].values())
    result["readme_commands"] = re.findall(
        r"```(?:bash|sh|shell|python)?\n([\s\S]*?)```", text
    )
    result["data_urls"] = sorted(set(re.findall(r'https?://[^\s<>"\)]+', text)))
    result["extensions"] = dict(Counter(p.suffix for p in paths))
    result["checkout_bytes"] = sum(p.stat().st_size for p in paths)
    save(WORK / row["id"] / "source-inventory.json", result)
    licenses = {k: v["sha256"] for k, v in result["licenses"].items()}
    return {
        "role": ROLES.get(row["repository"], "needs-classification"),
        "pin_origin": "registered-baseline"
        if row.get("recorded_commit")
        else "upstream-snapshot-2026-10-04",
        "license_files": licenses,
        "license_scope": "unresolved" if not licenses else "upstream-files-recorded",
        "dependencies": sorted(result["dependency_files"]),
        "native_test_files": len(result["test_files"]),
        "static_python": result["static_python"],
        "checkout_bytes": result["checkout_bytes"],
        "source_inventory": f"research/.work/simulator-evaluation/{row['id']}/source-inventory.json",
        "upstream_tree": f"https://github.com/{row['repository']}/tree/{row['commit']}",
    }


def main():
    data = load(REGISTRY)
    for row in data["candidates"]:
        if row["status"] != "attached":
            continue
        row.update(inspect(row))
        row.pop("acquisition_error", None)
        print(
            row["id"], row["role"], row["native_test_files"], "test files", flush=True
        )
    save(REGISTRY, data)


if __name__ == "__main__":
    main()
