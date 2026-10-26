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
import zipfile

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
    "r-library",
    "browser-profile",
    "browser-profile-locked",
    "browser-profile-native",
    "browser-tmp",
    "browser-tools",
    "pytest-cache",
    "pytest-tmp",
    "pytest-observer-cache",
    "pytest-observer-tmp",
    "pytest-observer-tmp-retry",
    "verifier-fixture",
    ".pytest_cache",
    "__pycache__",
}
RUN = re.compile(r"20\d{6}T\d{6}Z-.+")
SNNTORCH_ARCHIVE_SHA256 = (
    "b9d64db5652e980c990f452db1ccab9831040fdd73a968fe525338573ee1a360"
)


def windows_bind_source(value):
    """Normalize Docker Desktop's Linux spelling of a Windows bind source."""
    match = re.fullmatch(
        r"/(?:run/desktop/mnt/host|host_mnt|mnt)/([A-Za-z])/(.*)", value
    )
    return match[1].upper() + ":/" + match[2] if match else value


def io_path(path):
    """Use Win32 extended paths after the target's workspace check."""
    if os.name != "nt":
        return path
    text = str(path.absolute())
    if text.startswith("\\\\?\\"):
        return path
    if text.startswith("\\\\"):
        return path.__class__("\\\\?\\UNC\\" + text[2:])
    return path.__class__("\\\\?\\" + text)


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
    if io_path(path).is_file():
        return io_path(path).stat().st_size
    total = 0
    for parent, _, files in os.walk(io_path(path)):
        for name in files:
            file = path.__class__(parent) / name
            total += file.lstat().st_size
    return total


def remove_tree(path):
    """Remove directory entries without following Windows/WSL reparse points."""
    for entry in os.scandir(io_path(path)):
        child = path / entry.name
        info = entry.stat(follow_symlinks=False)
        attributes = getattr(info, "st_file_attributes", 0)
        if attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            if attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10):
                os.rmdir(io_path(child))
            else:
                io_path(child).unlink()
        elif entry.is_dir(follow_symlinks=False):
            remove_tree(child)
        else:
            if attributes & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x1):
                # Julia marks regular artifact files read-only. The containing
                # disposable tree was already checked; never chmod reparse points.
                os.chmod(io_path(child), stat.S_IREAD | stat.S_IWRITE)
            io_path(child).unlink()
    io_path(path).rmdir()


def running_mounts():
    ids = docker("ps", "-q").splitlines()
    if not ids:
        return []
    return [
        ROOT.__class__(
            windows_bind_source(m["Source"]) if os.name == "nt" else m["Source"]
        ).resolve()
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


def build_cache_targets(source, tracked):
    """Keep any directory containing pinned source, even if named build/dist."""
    result = []
    for path in [
        source / "build",
        source / "dist",
        *source.glob("*.egg-info"),
        *source.glob("src/*.egg-info"),
        source / "web/wasm/pkg",
        source / "web/wasm/target",
        source / "doom-ui/dist",
        source / "doom-ui/.wrangler",
        source / "tools/vizdoom-observer",
    ]:
        prefix = path.relative_to(source).as_posix() + "/"
        if path.is_dir() and not any(name.startswith(prefix) for name in tracked):
            result.append(path)
    return result


def disposable_targets(registry, sid=None):
    targets = []
    for row in registry["candidates"]:
        if sid and row["id"] != sid:
            continue
        auxiliary = WORK / row["id"] / "visual-followup"
        receipt = auxiliary / "runtime.json"
        if receipt.is_file():
            identity = load(receipt)
            if identity.get("owner") != "simctl" or identity.get("id") != row["id"]:
                raise ValueError("Auxiliary cleanup ownership mismatch")
            if identity.get("status") == "completed":
                names = identity.get("disposable", [])
                if not names or not set(names).issubset({"env", "mpl"}):
                    raise ValueError("Unqualified auxiliary cleanup directory")
                outputs = identity.get("outputs", [])
                if not outputs:
                    raise ValueError("Auxiliary cleanup needs retained output proof")
                for item in outputs:
                    path = checked_target(ROOT / item["path"])
                    if (
                        not path.is_relative_to((WORK / row["id"]).resolve())
                        or path.is_relative_to(auxiliary.resolve())
                        or not path.is_file()
                        or digest(path) != item["sha256"]
                    ):
                        raise ValueError(
                            "Auxiliary output changed; preserve environment"
                        )
                targets += [
                    auxiliary / name for name in names if (auxiliary / name).is_dir()
                ]
                cache = WORK / row["id"] / "pip-cache"
                if cache.is_dir():
                    targets.append(cache)
        for run in (WORK / row["id"]).iterdir():
            if not run.is_dir() or not RUN.fullmatch(run.name):
                continue
            targets += [p for p in run.iterdir() if p.name in DISPOSABLE and p.is_dir()]
            targets += [
                p
                for p in run.iterdir()
                if p.is_dir() and p.name.startswith("browser-profile-")
            ]
            source = run / "source"
            data_caches = [
                p
                for name in ("weight_coo.pkl", "weight_csr.pkl")
                if row["id"] == "SIM-015" and (p := source / "data" / name).is_file()
            ]
            if source.is_dir() and (
                (source / "build").exists()
                or (source / "dist").exists()
                or list(source.glob("*.egg-info"))
                or list(source.glob("src/*.egg-info"))
                or data_caches
                or (source / "web/wasm/pkg").exists()
                or (source / "web/wasm/target").exists()
                or (source / "doom-ui/dist").exists()
                or (source / "doom-ui/.wrangler").exists()
                or (source / "tools/vizdoom-observer").exists()
            ):
                tracked = subprocess.check_output(
                    ["git", "ls-files", "-z"],
                    cwd=ROOT / row["path"],
                    encoding="utf-8",
                    timeout=30,
                    env=dict(os.environ, GIT_NO_LAZY_FETCH="1"),
                ).split("\0")
                targets += build_cache_targets(source, tracked)
                targets += [
                    p
                    for p in data_caches
                    if p.relative_to(source).as_posix() not in tracked
                ]
            trees = [
                run / name
                for name in (
                    "source",
                    "probes",
                    "extra-probes",
                    "export",
                    "replay-export",
                )
            ]
            trees += [
                p
                for p in run.iterdir()
                if p.is_dir()
                and p.name.startswith(("review-", "check-", "supplement-"))
            ]
            for tree in trees:
                if not tree.is_dir():
                    continue
                for parent, dirs, _ in os.walk(tree):
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
    elif (WORK / "pip-cache").is_dir():
        # The evaluator mounts this owned cache for every Python SIM. A scoped
        # cleanup must not leave wheels from each completed candidate behind;
        # remove_targets still protects mounts of any running trial.
        targets.append(WORK / "pip-cache")
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


def pinned_input_pairs(row, commit, files, leaf_only=False):
    """Remove source replicas only after checking a frozen manifest and retained bytes."""
    if not row.get("frozen_inputs"):
        return []
    base = checked_target(WORK / row["id"])
    reference = row["frozen_inputs"]
    path = checked_target(ROOT / reference["path"])
    if not path.is_relative_to(base) or digest(path) != reference["sha256"]:
        raise ValueError("Pinned input manifest changed; preserve every copy")
    manifest = load(path)
    if row["commit"] != commit or manifest["commit"] != commit:
        raise ValueError("Unreviewed input revision")
    inputs = {item["file"]: item for item in manifest["inputs"]}
    if set(inputs) != set(files):
        raise ValueError("Unreviewed pinned input set")
    pairs = []
    for name, item in inputs.items():
        if item["git_blob"] != files[name]:
            raise ValueError("Pinned input blob changed")
        right = checked_target(ROOT / item["primary"])
        expected = base / "assets" / (name.rsplit("/", 1)[-1] if leaf_only else name)
        if right != checked_target(expected):
            raise ValueError("Pinned retained input escaped its registered location")
        if not right.is_file() or digest(right) != item["sha256"]:
            continue
        for run in base.iterdir():
            if not RUN.fullmatch(run.name) or not run.is_dir():
                continue
            left = checked_target(run / "source" / name)
            if left.is_file() and digest(left) == item["sha256"]:
                pairs.append((left, right))
    return pairs


def duplicate_targets(sid=None, registry=None):
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
        base = WORK / "SIM-008"
        if (not sid or sid == "SIM-008") and base.is_dir():
            for run in base.iterdir():
                if run.is_dir() and RUN.fullmatch(run.name):
                    pairs.append(
                        ("SIM-008", run / "assets/v09" / name, base / "assets" / name)
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
    pairs.append(
        (
            "SIM-011",
            WORK
            / "SIM-011/20261025T161016Z-c1cfda/source/data/meta/banc_888_meta_20260521.parquet",
            WORK
            / "SIM-011/20261025T161359Z-e089f2/source/data/meta/banc_888_meta_20260521.parquet",
        )
    )
    # Replayed OpticLobe runs keep their qualified origin in a hashed manifest.
    # Only duplicate gzip inputs in data/ can be removed; the original stays.
    if not sid or sid == "SIM-010":
        base = WORK / "SIM-010"
        for run in base.iterdir():
            receipt = run / "codex-inputs.json"
            if not run.is_dir() or not RUN.fullmatch(run.name) or not receipt.is_file():
                continue
            reused = load(receipt)
            reference = reused.get("reuse")
            if not reference:
                continue
            manifest = checked_target(ROOT / reference["manifest"])
            if (
                not manifest.is_relative_to(base.resolve())
                or digest(manifest) != reference["sha256"]
            ):
                raise ValueError("Unqualified frozen-input origin")
            original = {item["file"]: item for item in load(manifest)["inputs"]}
            for item in reused["inputs"]:
                relative = item["file"]
                if (
                    not relative.startswith("data/Codex ")
                    or not relative.endswith(".csv.gz")
                    or relative not in original
                ):
                    raise ValueError("Unqualified duplicated Codex input")
                left = checked_target(run / relative)
                right = checked_target(manifest.parent / relative)
                if left != right and item["sha256"] == original[relative]["sha256"]:
                    pairs.append(("SIM-010", left, right))
    if registry and (not sid or sid == "SIM-013"):
        row = next(x for x in registry["candidates"] if x["id"] == "SIM-013")
        reference = row.get("frozen_inputs")
        if reference:
            base = WORK / "SIM-013"
            manifest = checked_target(ROOT / reference["path"])
            if (
                not manifest.is_relative_to(base.resolve())
                or digest(manifest) != reference["sha256"]
            ):
                raise ValueError("Unqualified frozen ESN manifest")
            canonical = load(manifest)
            original = {x["file"]: x for x in canonical["inputs"]}
            expected = {
                f"inputs/{stage}/{group}.csv"
                for stage in ("larva", "adult")
                for group in ("connectome", "random", "cfg")
            }
            if canonical["commit"] != row["commit"] or set(original) != expected:
                raise ValueError("Frozen ESN matrix set mismatch")
            for run in base.iterdir():
                receipt = run / "conn-esn-inputs.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                candidate = load(receipt)
                if candidate["commit"] != canonical["commit"]:
                    continue
                for item in candidate["inputs"]:
                    relative = item["file"]
                    if relative not in original or any(
                        item[k] != original[relative][k] for k in ("sha256", "git_blob")
                    ):
                        continue
                    left = checked_target(run / relative)
                    right = checked_target(manifest.parent / relative)
                    if left != right:
                        pairs.append(("SIM-013", left, right))
    if registry and (not sid or sid == "SIM-015"):
        row = next((x for x in registry["candidates"] if x["id"] == "SIM-015"), None)
        reference = row.get("frozen_inputs") if row else None
        if reference:
            base = WORK / "SIM-015"
            manifest = checked_target(ROOT / reference["path"])
            if (
                not manifest.is_relative_to(base.resolve())
                or digest(manifest) != reference["sha256"]
            ):
                raise ValueError("Unqualified frozen claude-fly manifest")
            canonical = load(manifest)
            if canonical["commit"] != row["commit"]:
                raise ValueError("Frozen claude-fly commit mismatch")
            original = {x["path"]: x for x in canonical["inputs"]}
            for run in base.iterdir():
                receipt = run / "claude-inputs.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                candidate = load(receipt)
                if candidate["commit"] != canonical["commit"]:
                    continue
                for item in candidate["inputs"]:
                    relative = item["path"]
                    if item.get("status") == "unavailable" or relative not in original:
                        continue
                    registered = original[relative]
                    if item["sha256"] != registered["sha256"] or relative not in {
                        "data/2025_Connectivity_783.parquet",
                        "data/2025_Completeness_783.csv",
                        "data/plastic_weights.pt",
                        "data/plastic_weights_fly0.pt",
                        "data/plastic_weights_fly1.pt",
                    }:
                        continue
                    left = checked_target(run / "source" / relative)
                    # Retain one exact LF-derived CSV; the CRLF primary is distinct.
                    right = checked_target(
                        manifest.parent / "source" / relative
                        if relative.endswith("Completeness_783.csv")
                        else ROOT / registered["primary"]
                    )
                    if (
                        left != right
                        and right.is_file()
                        and digest(right) == registered["sha256"]
                    ):
                        pairs.append(("SIM-015", left, right))
    if registry and (not sid or sid == "SIM-016"):
        row = next((x for x in registry["candidates"] if x["id"] == "SIM-016"), None)
        if row:
            for run in (WORK / "SIM-016").iterdir():
                receipt = run / "result.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                result = load(receipt)
                if result.get("commit") != row["commit"]:
                    continue
                for item in result.get("profile", {}).get("assets", []):
                    if item["destination"] not in {
                        "malecns/body-annotations.feather",
                        "malecns/body-nt.feather",
                        "malecns/connectome-weights.feather",
                    }:
                        continue
                    left = checked_target(run / "assets" / item["destination"])
                    right = checked_target(WORK / item["source"])
                    if (
                        left != right
                        and right.is_file()
                        and digest(right) == item["sha256"]
                    ):
                        pairs.append(("SIM-016", left, right))
    if registry and (not sid or sid == "SIM-017"):
        from probes.flywire_assets import NAMES

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-017"), None)
        base = WORK / "SIM-017"
        if row and base.is_dir():
            for run in base.iterdir():
                receipt = run / "v630-inputs.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                manifest = load(receipt)
                if manifest.get("commit") != row["commit"]:
                    continue
                for item in manifest.get("files", []):
                    name = item["file"]
                    if name not in NAMES:
                        raise ValueError("Unqualified v630 duplicate filename")
                    left = checked_target(run / "source/v630_data" / name)
                    right = checked_target(ROOT / item["primary"])
                    if right != (base / "assets" / name).resolve():
                        raise ValueError("Unqualified v630 retained primary")
                    if right.is_file() and digest(right) == item["sha256"]:
                        pairs.append(("SIM-017", left, right))
    if registry and (not sid or sid == "SIM-019"):
        from probes.scalebreak_assets import FILES, PREFIX, SHA256

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-019"), None)
        base = WORK / "SIM-019"
        archive = base / "assets/results_pretrained_models.zip"
        if row and base.is_dir() and archive.is_file():
            if digest(archive) != SHA256:
                raise ValueError(
                    "Retained pretrained archive changed; preserve all copies"
                )
            import hashlib

            with zipfile.ZipFile(archive) as bundle:
                expected = {
                    PREFIX + name: hashlib.sha256(
                        bundle.read(PREFIX + name)
                    ).hexdigest()
                    for name in FILES
                }
            retained = {}
            for run in sorted(base.iterdir()):
                receipt = run / "pretrained-inputs.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                manifest = load(receipt)
                if (
                    manifest.get("sha256") != SHA256
                    or manifest.get("model") != "flow/0000/000"
                ):
                    continue
                for item in manifest.get("files", []):
                    member = item["member"]
                    if member not in expected or item["sha256"] != expected[member]:
                        raise ValueError("Unqualified pretrained model member")
                    left = checked_target(run / item["destination"])
                    if left != (run / "assets/pretrained" / member).resolve():
                        raise ValueError("Unqualified pretrained model copy path")
                    if not left.is_file() or digest(left) != expected[member]:
                        continue
                    right = retained.setdefault(member, left)
                    if left != right:
                        pairs.append(("SIM-019", left, right))
    if registry and (not sid or sid == "SIM-022"):
        from probes.snntorch_assets import COMMIT, FILES

        base = WORK / "SIM-022"
        archive = base / "assets" / (COMMIT + ".zip")
        if archive.is_file():
            if digest(archive) != SNNTORCH_ARCHIVE_SHA256:
                raise ValueError(
                    "Retained snnTorch archive changed; preserve all copies"
                )
            import hashlib

            with zipfile.ZipFile(archive) as bundle:
                expected = {
                    name: hashlib.sha256(
                        bundle.read("fly-brain-snntorch-" + COMMIT + "/" + name)
                    ).hexdigest()
                    for name in FILES
                }
            retained = {}
            for run in sorted(base.iterdir()):
                receipt = run / "pinned-assets.json"
                if (
                    not run.is_dir()
                    or not RUN.fullmatch(run.name)
                    or not receipt.is_file()
                ):
                    continue
                manifest = load(receipt)
                if (
                    manifest.get("commit") != COMMIT
                    or manifest.get("archive_sha256") != SNNTORCH_ARCHIVE_SHA256
                ):
                    continue
                for item in manifest["files"]:
                    name = item["file"]
                    if name not in expected or item["sha256"] != expected[name]:
                        raise ValueError("Unqualified snnTorch input copy")
                    left = checked_target(run / "source" / name)
                    if left.is_file() and digest(left) == expected[name]:
                        right = retained.setdefault(name, left)
                        if left != right:
                            pairs.append(("SIM-022", left, right))
    if registry and (not sid or sid == "SIM-023"):
        row = next((x for x in registry["candidates"] if x["id"] == "SIM-023"), None)
        if row and row.get("frozen_inputs"):
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if digest(manifest_path) != reference["sha256"]:
                raise ValueError("DoomFly frozen input identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != row["commit"]:
                raise ValueError("DoomFly frozen input commit differs")
            for item in manifest["inputs"]:
                right = checked_target(ROOT / item["reused_from"])
                if not right.is_relative_to((WORK / "SIM-001").resolve()):
                    raise ValueError(
                        "DoomFly primary must be the retained SIM-001 input"
                    )
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in (WORK / "SIM-023").iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    left = checked_target(
                        run / "source/connectome_data/malecns_v1" / item["name"]
                    )
                    if left.is_file() and digest(left) == item["sha256"]:
                        pairs.append(("SIM-023", left, right))
    if registry and (not sid or sid == "SIM-024"):
        from probes.shiu_assets import FILES

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-024"), None)
        if row and row.get("frozen_inputs"):
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if digest(manifest_path) != reference["sha256"]:
                raise ValueError("Shiu frozen input identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != row["commit"]:
                raise ValueError("Shiu frozen input commit differs")
            for item in manifest["inputs"]:
                name = item["file"]
                if name not in FILES or item["git_blob"] != FILES[name]:
                    raise ValueError("Unknown original Shiu input")
                right = checked_target(ROOT / item["primary"])
                if not any(
                    right.is_relative_to((WORK / directory).resolve())
                    for directory in ("SIM-022", "SIM-024/assets")
                ):
                    raise ValueError("Shiu primary must be the verified retained input")
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in (WORK / "SIM-024").iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    left = checked_target(run / "source" / name)
                    if left.is_file() and digest(left) == item["sha256"]:
                        pairs.append(("SIM-024", left, right))
    if registry and (not sid or sid == "SIM-025"):
        from probes.mbi_download import IDENTITY, catalog_identity

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-025"), None)
        if row and row.get("frozen_inputs"):
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if digest(manifest_path) != reference["sha256"]:
                raise ValueError("MBI frozen input identity changed")
            manifest = load(manifest_path)
            if (
                manifest["project"] != "9hxwe"
                or catalog_identity(manifest["files"]) != IDENTITY
            ):
                raise ValueError("Unreviewed MBI release")
            base = WORK / "SIM-025"
            for item in manifest["files"]:
                right = checked_target(ROOT / item["primary"])
                if right != checked_target(base / "assets/data" / item["path"]):
                    raise ValueError(
                        "MBI retained primary must be the registered OSF file"
                    )
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in base.iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    left = checked_target(run / "source/data" / item["path"])
                    if left.is_file() and digest(left) == item["sha256"]:
                        pairs.append(("SIM-025", left, right))
    if registry and (not sid or sid == "SIM-026"):
        from probes.flyconnectome_assets import COMMIT

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-026"), None)
        if row and row.get("frozen_inputs"):
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if digest(manifest_path) != reference["sha256"]:
                raise ValueError("FlyConnectome frozen export identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != COMMIT or row["commit"] != COMMIT:
                raise ValueError("Unreviewed FlyConnectome commit")
            base = (WORK / "SIM-026").resolve()
            retained = {
                item["path"]: item["sha256"] for item in manifest["normalized_exports"]
            }
            for item in manifest["verified_replicas"]:
                left = checked_target(ROOT / item["duplicate"])
                right = checked_target(ROOT / item["retained"])
                if not left.is_relative_to(base) or not right.is_relative_to(base):
                    raise ValueError(
                        "FlyConnectome duplicate must stay inside its candidate"
                    )
                if (
                    item["retained"] not in retained
                    or retained[item["retained"]] != item["sha256"]
                    or left == right
                ):
                    raise ValueError(
                        "FlyConnectome duplicate has no matching retained primary"
                    )
                if (
                    right.is_file()
                    and digest(right) == item["sha256"]
                    and left.is_file()
                    and digest(left) == item["sha256"]
                ):
                    pairs.append(("SIM-026", left, right))
    if registry and (not sid or sid == "SIM-027"):
        from probes.pugliese_assets import COMMIT, FILES

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-027"), None)
        if row and row.get("frozen_inputs"):
            base = (WORK / "SIM-027").resolve()
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if (
                not manifest_path.is_relative_to(base)
                or digest(manifest_path) != reference["sha256"]
            ):
                raise ValueError("Pugliese frozen input identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != COMMIT or row["commit"] != COMMIT:
                raise ValueError("Unreviewed Pugliese commit")
            inputs = {item["file"]: item for item in manifest["inputs"]}
            if set(inputs) != set(FILES):
                raise ValueError("Unreviewed Pugliese input set")
            for name, (oid, size) in FILES.items():
                item = inputs[name]
                if item["git_blob"] != oid or item["bytes"] != size:
                    raise ValueError("Pugliese frozen blob differs")
                right = checked_target(ROOT / item["primary"])
                if right != checked_target(base / "assets" / name.rsplit("/", 1)[1]):
                    raise ValueError("Pugliese retained input path differs")
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in base.iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    left = checked_target(run / "source" / name)
                    if left.is_file() and digest(left) == item["sha256"]:
                        pairs.append(("SIM-027", left, right))
    if registry and (not sid or sid == "SIM-029"):
        from probes.snedea_assets import COMMIT, FILES

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-029"), None)
        if row and row.get("frozen_inputs"):
            base = (WORK / "SIM-029").resolve()
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if (
                not manifest_path.is_relative_to(base)
                or digest(manifest_path) != reference["sha256"]
            ):
                raise ValueError("Snedea frozen input identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != COMMIT or row["commit"] != COMMIT:
                raise ValueError("Unreviewed snedea commit")
            inputs = {item["file"]: item for item in manifest["inputs"]}
            if set(inputs) != {"data/" + name for name in FILES}:
                raise ValueError("Unreviewed snedea input set")
            for name, oid in FILES.items():
                item = inputs["data/" + name]
                if item["git_blob"] != oid:
                    raise ValueError("Snedea input blob differs")
                right = checked_target(ROOT / item["primary"])
                if right != checked_target(base / "assets" / name):
                    raise ValueError("Snedea retained input path differs")
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in base.iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    for folder in ["source/data", "assets"]:
                        left = checked_target(run / folder / name)
                        if left.is_file() and digest(left) == item["sha256"]:
                            pairs.append(("SIM-029", left, right))
    if registry and (not sid or sid == "SIM-030"):
        from probes.fcta_assets import COMMIT, pinned_tree

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-030"), None)
        if row and row.get("frozen_inputs"):
            base = (WORK / "SIM-030").resolve()
            reference = row["frozen_inputs"]
            manifest_path = checked_target(ROOT / reference["path"])
            if (
                not manifest_path.is_relative_to(base)
                or digest(manifest_path) != reference["sha256"]
            ):
                raise ValueError("FCTA frozen input identity changed")
            manifest = load(manifest_path)
            if manifest["commit"] != COMMIT or row["commit"] != COMMIT:
                raise ValueError("Unreviewed FCTA commit")
            tree = pinned_tree(ROOT / row["path"])
            inputs = {item["file"]: item for item in manifest["inputs"]}
            if set(inputs) != set(tree):
                raise ValueError("FCTA frozen bundle set differs")
            for name, item in inputs.items():
                if item["git_blob"] != tree[name]:
                    raise ValueError("FCTA input blob differs")
                right = checked_target(ROOT / item["primary"])
                if right != checked_target(base / "assets/bundle" / name):
                    raise ValueError("FCTA retained input path differs")
                if not right.is_file() or digest(right) != item["sha256"]:
                    continue
                for run in base.iterdir():
                    if not RUN.fullmatch(run.name):
                        continue
                    left = checked_target(run / "source" / name)
                    if left.is_file() and digest(left) == item["sha256"]:
                        pairs.append(("SIM-030", left, right))
    if registry and (not sid or sid == "SIM-002"):
        from probes.fitting_assets import ARCHIVE_SHA256, FILES

        row = next((x for x in registry["candidates"] if x["id"] == "SIM-002"), None)
        if row and row.get("frozen_inputs"):
            base = checked_target(WORK / "SIM-002")
            reference = row["frozen_inputs"]
            path = checked_target(ROOT / reference["path"])
            if not path.is_relative_to(base) or digest(path) != reference["sha256"]:
                raise ValueError("Fitting frozen input identity changed")
            manifest = load(path)
            archive = checked_target(ROOT / manifest["archive"])
            if (
                manifest["commit"] != row["commit"]
                or manifest["archive_sha256"] != ARCHIVE_SHA256
                or archive != base / "assets/author-data.rar"
            ):
                raise ValueError("Unqualified fitting archive or revision")
            inputs = {item["member"]: item for item in manifest["inputs"]}
            if set(inputs) != set(FILES):
                raise ValueError("Unqualified fitting input set")
            if archive.is_file() and digest(archive) == ARCHIVE_SHA256:
                for name, item in inputs.items():
                    primary = checked_target(ROOT / item["primary"])
                    if (
                        primary != base / "assets/author" / name
                        or item["bytes"] != FILES[name]
                    ):
                        raise ValueError("Unqualified fitting retained input")
                    if not primary.is_file() or digest(primary) != item["sha256"]:
                        continue
                    for run in base.iterdir():
                        if RUN.fullmatch(run.name):
                            copy = checked_target(run / "source/data" / name)
                            if copy.is_file() and digest(copy) == item["sha256"]:
                                pairs.append(("SIM-002", copy, primary))
    if registry:
        from probes import data_prep_assets, flyvis_assets, wormvae_assets

        for candidate_id, module, leaf_only in [
            ("SIM-031", flyvis_assets, True),
            ("SIM-032", wormvae_assets, False),
            ("SIM-033", data_prep_assets, False),
        ]:
            if sid and sid != candidate_id:
                continue
            row = next(
                (x for x in registry["candidates"] if x["id"] == candidate_id), None
            )
            if row:
                pairs += [
                    (candidate_id, left, right)
                    for left, right in pinned_input_pairs(
                        row, module.COMMIT, module.FILES, leaf_only
                    )
                ]
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
    volumes = docker(
        "volume", "ls", "-q", "--filter", "label=aspa.simulation.owner=simctl"
    ).splitlines()
    for name in volumes:
        info = json.loads(docker("volume", "inspect", name))[0]
        if (
            not name.startswith("aspa-sim-")
            or (info.get("Labels") or {}).get("aspa.simulation.owner") != "simctl"
        ):
            continue
        references = docker("ps", "-aq", "--filter", "volume=" + name).splitlines()
        item = {
            "volume": name,
            "container_references": references,
            "status": "kept_container_reference" if references else "planned",
        }
        if apply and not references:
            try:
                docker("volume", "rm", name)
                item["status"] = "removed"
            except subprocess.CalledProcessError as exc:
                # A new container may mount the volume after the observation.
                # Docker's non-forced rm refuses such a race.
                item.update(status="kept_in_use_or_error", exit_code=exc.returncode)
        results.append(item)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--id")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Also remove unused owned simulator images, volumes and stopped containers",
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
    for left, right in duplicate_targets(args.id, registry):
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
                blocked = blocked or any(
                    item.get("volume", "").startswith(
                        "aspa-sim-" + row["id"].lower() + "-"
                    )
                    and item["status"]
                    in {"kept_container_reference", "kept_in_use_or_error"}
                    for item in receipt["docker"]
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
