"""Remove owned disposable run state; preserve results and one copy of inputs.

Default is a plan. --apply executes it. All deletion targets must resolve strictly
below the simulation work area; running container mounts and proof files are kept.
Docker cleanup is restricted to explicitly owned simulator containers/image tags.
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import time

from inventory import load, save
from paths import REGISTRY, ROOT, WORK
from publish_artifacts import digest

DISPOSABLE = {
    "env",
    "tmp",
    "cache",
    "npm-cache",
    "apt-cache",
    "apt-lists",
    "home",
    "mpl",
    "browser-profile",
    "pytest-cache",
    "pytest-tmp",
    ".pytest_cache",
    "__pycache__",
}
RUN = re.compile(r"20\d{6}T\d{6}Z-.+")


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], encoding="utf-8", timeout=30
    ).strip()


def checked_target(path):
    resolved = path.resolve()
    if (
        resolved == WORK.resolve()
        or not resolved.is_relative_to(WORK.resolve())
        or path.is_symlink()
    ):
        raise ValueError(f"Refusing unsafe cleanup target: {path}")
    return resolved


def size_of(path):
    if path.is_file():
        return path.stat().st_size
    total = 0
    for parent, _, files in os.walk(path):
        for name in files:
            file = path.__class__(parent) / name
            total += file.lstat().st_size
    return total


def remove_tree(path):
    """Remove directory entries without following Windows/WSL reparse points."""
    for entry in os.scandir(path):
        child = path / entry.name
        info = entry.stat(follow_symlinks=False)
        attributes = getattr(info, "st_file_attributes", 0)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            if attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10):
                os.rmdir(child)
            else:
                child.unlink()
        elif entry.is_dir(follow_symlinks=False):
            remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def running_mounts():
    ids = docker("ps", "-q").splitlines()
    if not ids:
        return []
    return [
        ROOT.__class__(m["Source"]).resolve()
        for c in json.loads(docker("inspect", *ids))
        for m in c.get("Mounts", [])
        if m.get("Type") == "bind"
    ]


def protected_paths(registry):
    paths = {REGISTRY.resolve()}
    for row in registry["candidates"]:
        references = list(row.get("launch_review", {}).get("receipts", []))
        references += [row.get("evaluation", {}).get("result", "")]
        references += [v["source"] for v in row.get("visual_artifacts", [])]
        for relative in references:
            path = ROOT / relative
            if path.is_file():
                paths.add(path.resolve())
    return paths


def disposable_targets(registry, sid=None):
    targets = []
    for row in registry["candidates"]:
        if sid and row["id"] != sid:
            continue
        for run in (WORK / row["id"]).iterdir():
            if not run.is_dir() or not RUN.fullmatch(run.name):
                continue
            targets += [p for p in run.iterdir() if p.name in DISPOSABLE and p.is_dir()]
            source = run / "source"
            if source.is_dir():
                for parent, dirs, _ in os.walk(source):
                    for name in list(dirs):
                        if name in {"node_modules", "__pycache__", ".pytest_cache"}:
                            targets.append(ROOT.__class__(parent) / name)
                            dirs.remove(name)
    if not sid:
        targets += [
            WORK / name
            for name in ("pip-cache", "npm-cache", "tool-cache")
            if (WORK / name).is_dir()
        ]
    if not sid or sid == "SIM-009":
        driver = WORK / "browser-tools/node_modules"
        if driver.is_dir():
            targets.append(driver)
        npm_cache = WORK / "npm-cache"
        if sid and npm_cache.is_dir():
            targets.append(npm_cache)
    return targets


def remove_targets(targets, protected, active, apply=False):
    results = []
    for path in targets:
        path = checked_target(path)
        if any(p == path or p.is_relative_to(path) for p in protected):
            results.append({"path": str(path), "status": "kept_proof"})
            continue
        if any(path.is_relative_to(m) or m.is_relative_to(path) for m in active):
            results.append({"path": str(path), "status": "kept_active_mount"})
            continue
        if not path.exists():
            continue
        item = {
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": size_of(path),
            "status": "planned",
        }
        if apply:
            if path.is_dir():
                try:
                    remove_tree(path)
                except OSError as exc:
                    item.update(status="failed", reason=str(exc))
                    results.append(item)
                    continue
            else:
                path.unlink()
            item["status"] = "removed"
        results.append(item)
    return results


def duplicate_targets(sid=None):
    """Known run-input copies only; generated results and published files excluded."""
    pairs = []
    run1 = WORK / "SIM-001/20261005T105111Z-6999dc/connectome/raw"
    run7 = WORK / "SIM-007/20261025T110749Z-7c38a9/assets/malecns"
    for name, canonical in [
        (
            "connectome-weights.feather",
            "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
        ),
        ("body-nt.feather", "body-neurotransmitters-male-cns-v1.0.feather"),
        (
            "body-annotations.feather",
            "body-annotations-male-cns-v1.0-minconf-0.5.feather",
        ),
    ]:
        pairs.append(("SIM-007", run7 / name, run1 / canonical))
    for name in (
        "connectome-weights-male-cns-v0.9-minconf-0.5.feather",
        "body-annotations-male-cns-v0.9-minconf-0.5.feather",
    ):
        pairs.append(
            (
                "SIM-008",
                WORK / "SIM-008/20261025T113426Z-3ab3f7/assets/v09" / name,
                WORK / "SIM-008/assets" / name,
            )
        )
    pairs.append(
        (
            "SIM-029",
            WORK / "SIM-029/20261004T212712Z-172e2c/assets/snedea/connectome.bin.gz",
            WORK / "SIM-029/assets/connectome.bin.gz",
        )
    )
    for name in ("2025_Connectivity_783.parquet", "2025_Proofread_783.csv"):
        pairs.append(
            (
                "SIM-006",
                WORK / "SIM-006/20261025T103446Z-a3ced1/source/data" / name,
                WORK / "SIM-006/20261025T103703Z-5caefe/source/data" / name,
            )
        )
    return [
        (left, right)
        for owner, left, right in pairs
        if (not sid or sid == owner) and left.is_file() and right.is_file()
    ]


def cleanup_docker(apply=False):
    results = []
    ids = docker(
        "ps", "-aq", "--filter", "label=aspa.simulation.owner=simctl"
    ).splitlines()
    for cid in ids:
        record = json.loads(docker("inspect", cid))[0]
        if record["State"]["Running"] or not record["Name"].startswith("/aspa-sim-"):
            continue
        results.append({"container": cid, "status": "removed" if apply else "planned"})
        if apply:
            docker("rm", cid)
    images = docker(
        "image",
        "ls",
        "--filter",
        "reference=aspa-sim-*",
        "--format",
        "{{.Repository}}:{{.Tag}}",
    ).splitlines()
    for tag in images:
        if not tag.startswith("aspa-sim-") or docker(
            "ps", "-aq", "--filter", "ancestor=" + tag
        ):
            continue
        results.append({"image": tag, "status": "removed" if apply else "planned"})
        if apply:
            docker("image", "rm", tag)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--id")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Also remove unused owned simulator images and stopped containers",
    )
    args = parser.parse_args()
    registry = load(REGISTRY)
    if args.id and args.id not in {r["id"] for r in registry["candidates"]}:
        parser.error("Unknown SIM ID")
    active = running_mounts()
    protected = protected_paths(registry)
    before_hashes = {str(p): digest(p) for p in protected}
    free_before = shutil.disk_usage(WORK).free
    targets = disposable_targets(registry, args.id)
    duplicates = []
    for left, right in duplicate_targets(args.id):
        if left.stat().st_size == right.stat().st_size and digest(left) == digest(
            right
        ):
            duplicates.append(
                {
                    "removed_copy": left.relative_to(ROOT).as_posix(),
                    "retained_copy": right.relative_to(ROOT).as_posix(),
                    "sha256": digest(right),
                }
            )
            targets.append(left)
    # These are derived caches; the registered input parquet and output spike exports stay intact.
    if not args.id or args.id == "SIM-006":
        targets += [
            p
            for name in ("weight_csr.pkl", "weight_coo.pkl")
            if (
                p := WORK / "SIM-006/20261025T103703Z-5caefe/source/data" / name
            ).is_file()
        ]
    receipt = {
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "apply": args.apply,
        "targets": [
            {"path": p.relative_to(ROOT).as_posix(), "bytes": size_of(p)}
            for p in targets
        ],
        "duplicates": duplicates,
        "free_before": free_before,
    }
    output = (
        WORK
        / "maintenance"
        / (time.strftime("cleanup-%Y%m%dT%H%M%SZ", time.gmtime()) + ".json")
    )
    save(output, receipt)
    receipt["results"] = remove_targets(targets, protected, active, args.apply)
    receipt["docker"] = cleanup_docker(args.apply) if args.docker else []
    # The registry is deliberately checked before adding the cleanup record.
    receipt["protected_files_unchanged"] = all(
        p.is_file() and digest(p) == before_hashes[str(p)] for p in protected
    )
    receipt["free_after"] = shutil.disk_usage(WORK).free
    receipt["removed_bytes"] = sum(
        p.get("bytes", 0) for p in receipt["results"] if p["status"] == "removed"
    )
    save(output, receipt)
    if not receipt["protected_files_unchanged"]:
        raise ValueError("Protected evidence changed during cleanup")
    if args.apply:
        latest = load(REGISTRY)
        for row in latest["candidates"]:
            if not args.id or args.id == row["id"]:
                blocked = any(
                    item["status"] in {"failed", "kept_active_mount", "kept_proof"}
                    and f"/{row['id']}/" in item["path"].replace("\\", "/")
                    for item in receipt["results"]
                )
                row["cleanup"] = {
                    "date": receipt["date"],
                    "receipt": output.relative_to(ROOT).as_posix(),
                    "status": "incomplete" if blocked else "completed",
                }
        save(REGISTRY, latest)
    print(
        json.dumps(
            {
                "receipt": output.relative_to(ROOT).as_posix(),
                "targets": len(targets),
                "removed_bytes": receipt["removed_bytes"],
                "free_before": free_before,
                "free_after": receipt["free_after"],
                "protected_files_unchanged": receipt["protected_files_unchanged"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
